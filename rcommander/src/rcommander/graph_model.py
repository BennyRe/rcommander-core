import roslib; roslib.load_manifest('rcommander')
import rospy
import tool_utils as tu
import glob
import os.path as pt
import cPickle as pk
import os
import smach
import outcome_tool as ot
import graph
import sm_thread_runner as smtr

def is_container(node):
    return hasattr(node, 'get_child_name') 

class FSMDocument:
    count = 0
    @staticmethod
    def new_document():
        d = FSMDocument('untitled' + str(FSMDocument.count), False, False)
        FSMDocument.count = FSMDocument.count + 1
        return d

    def __init__(self, filename, modified, real_filename=False):
        self.filename = filename
        self.modified = modified
        self.real_filename = real_filename

    def get_name(self):
        return pt.split(self.filename)[1]

    def get_filename(self):
        return self.filename

    def set_filename(self, fn):
        self.filename = fn

    def has_real_filename(self):
        return self.real_filename

class GraphModel:

    #Information about graph connectivity
    EDGES_FILE = 'edges.graph'

    #Misc information about graph itself
    NODES_FILE = 'nodes.graph'

    NODE_RADIUS = 14

    EDGE_LENGTH = 2.

    def __init__(self):
        self.gve = graph.create(depth=True)
        self.smach_states = {}
        self.start_state = None
        self.node = self.gve.node
        self.edge = self.gve.edge

        self.sm_thread = {}
        self.add_outcome(tu.InfoStateBase.GLOBAL_NAME)
        self.document = FSMDocument.new_document()

    def get_start_state(self):
        return self.start_state

    def set_start_state(self, state):
        if state == tu.InfoStateBase.GLOBAL_NAME or issubclass(self.smach_states[state].__class__, tu.InfoStateBase):
            raise RuntimeError("Can\'t make info states start states")
        self.start_state = state

    def set_document(self, document):
        self.document = document

    @staticmethod
    def load(name):
        state_pkl_names = glob.glob(pt.join(name, '*.state'))

        gm = GraphModel()
        gm.smach_states = {}

        #Get meta info
        nodes_fn = pt.join(name, GraphModel.NODES_FILE)
        pickle_file = open(nodes_fn, 'r')
        info = pk.load(pickle_file)
        gm.start_state = info['start_state']
        states_to_load = set(info['state_names'])

        #Load individual states
        for fname in state_pkl_names:
            sname = pt.splitext(pt.split(fname)[1])[0]
            if not states_to_load.issuperset([sname]):
                continue

            pickle_file = open(fname, 'r')
            rospy.loginfo('Loading state %s' % sname)
            gm.smach_states[sname] = pk.load(pickle_file)
            gm.gve.add_node(sname, GraphModel.NODE_RADIUS)
            pickle_file.close()

            if is_container(gm.smach_states[sname]):
                gm.smach_states[sname] = gm.smach_states[sname].load_and_recreate()
                if sname == 'gripper_event0':
                    print "gripper_event0 REMAPPING IS"
                    print gm.smach_states[sname].remapping

        #Reconstruct graph
        graph_name = pt.join(name, GraphModel.EDGES_FILE)
        pickle_file = open(graph_name, 'r')
        edges = pk.load(pickle_file)
        pickle_file.close()
        for node1, node2, n1_outcome in edges:
            gm.gve.add_edge(node1, node2, label=n1_outcome, length=GraphModel.EDGE_LENGTH)

        gm.set_document(FSMDocument(name, modified=False, real_filename=True))
        return gm

    def save(self, name):
        print '@@@ saving to', name
        if not pt.exists(name):
            os.mkdir(name)

        #Save each state
        for state_name in self.smach_states.keys():
            if is_container(self.smach_states[state_name]):
                self.smach_states[state_name].save_child(name)

            state_fname = pt.join(name, state_name) + '.state'
            pickle_file = open(state_fname, 'w')
            pk.dump(self.smach_states[state_name], pickle_file)
            pickle_file.close()

            if is_container(self.smach_states[state_name]):
                print 'document\'s path was', self.smach_states[state_name].document.get_filename()
            #If the state has other stuff inside it
               # child_gm = self.smach_states[state_name].get_child()
               # # if this container has a path, save it to that path
               # if child_gm.document.has_real_filename():
               #     child_gm.save(child_gm.get_filename())
               # # if this container does not have a path
               # else:
               #     fname = pt.join(name, state_name)
               #     child_gm.save(fname)
               #     child_gm.document = FSMDocument(fname, modified=False, real_filename=True)

        #Save connections
        edge_list = []
        for e in self.gve.edges:
            edge_list.append([e.node1.id, e.node2.id, e.label])

        edge_fn = pt.join(name, GraphModel.EDGES_FILE)
        pickle_file = open(edge_fn, 'w')
        pk.dump(edge_list, pickle_file)
        pickle_file.close()

        nodes_fn = pt.join(name, GraphModel.NODES_FILE)
        pickle_file = open(nodes_fn, 'w')
        pk.dump({'start_state': self.start_state, 'state_names': self.smach_states.keys()}, pickle_file)
        pickle_file.close()

        self.document = FSMDocument(name, False, True)

    def create_singleton_statemachine(self, smach_state):
        #if self.get_start_state() == None:
        #    self.set_start_state(smach_state.name)
        sm = self.create_state_machine(ignore_start_state=True)
        temp_gm = GraphModel()
        temp_gm.add_node(smach_state)
        temp_gm.set_start_state(smach_state.name)
        return temp_gm.create_state_machine(sm.userdata)

    def run(self, name="", state_machine=None, userdata=None):
        if state_machine == None:
            sm = child_gm.create_state_machine(userdata=userdata)
        else:
            sm = state_machine

        rthread = smtr.ThreadRunSM(name, sm)
        self.sm_thread['run_sm'] = rthread
        self.sm_thread['preempted'] = None
        rthread.start()

    def create_state_machine(self, userdata=None, ignore_start_state=False):
        print '>>>>>>>>>>>>>> create_state_machine', userdata
        sm = smach.StateMachine(outcomes = self.outcomes())
        print 'sm userdata', sm.userdata
        for global_node_name in self.global_nodes(None):
            global_node = self.smach_states[global_node_name]
            global_variable_name = global_node.get_name()
            value = global_node.get_info()
            exec_str = "sm.userdata.%s = value" % global_variable_name
            print 'executing', exec_str
            exec exec_str

        #Copy over input userdata into our state machine so that nodes inside
        # us would have access
        if userdata != None:
            print 'userdata keys', userdata.keys()
            for key in userdata.keys():
                exec ("sm.userdata.%s = userdata.%s" % (key, key))
                print 'copying key', key
                exec ("print 'data in key is', sm.userdata.%s" % (key))

        with sm:
            for node_name in self.nonoutcomes():
                node = self.smach_states[node_name]
                if issubclass(node.__class__, tu.InfoStateBase):
                    continue

                transitions = {}
                print node_name, 'input keys', node.get_registered_input_keys()
                for e in self.gve.node(node_name).edges:
                    if e.node1.id == node_name:
                        transitions[e.label] = e.node2.id
                        #print e.node1.id, e.label, e.node2.id

                remapping = {}
                for input_key in node.get_registered_input_keys():
                    print 'source for', input_key, 'is', node.source_for(input_key)
                    remapping[input_key] = node.source_for(input_key)
                print '>> node_name', node_name, 'transitions', transitions, 'remapping', remapping
                smach.StateMachine.add(node_name, node, transitions=transitions, remapping=remapping)

        if ignore_start_state:
            return sm

        if self.start_state == None:
            raise RuntimeError('No start state set.')
        print 'create_state_machine start state is', self.start_state
        sm.set_initial_state([self.start_state])
        print '<<<<<<<<<<<<<<'
        return sm

    def nonoutcomes(self):
        noc = []
        for node_name in self.smach_states.keys():
            if self.smach_states[node_name].__class__ != ot.EmptyState:
                noc.append(node_name)
        return noc

    #@return a list of node names and outcomes
    #        e.g. [[edge_name, node_name], ...]
    def current_children_of(self, node_name):
        ret_list = []
        for edge in self.gve.node(node_name).edges:
            if edge.node1.id != node_name:
                continue
            ret_list.append([edge.label, edge.node2.id])
        return ret_list

    def outcomes(self):
        #all empty states are outcomes
        oc = []
        for node_name in self.smach_states.keys():
            if self.smach_states[node_name].__class__ == ot.EmptyState and node_name != tu.InfoStateBase.GLOBAL_NAME:
                oc.append(node_name)
        #print 'outcomes', oc
        return oc

    def pop_smach_state(self, node_name):
        return self.smach_states.pop(node_name)

    def get_smach_state(self, node_name):
        #print self.smach_states.keys()
        return self.smach_states[node_name]

    def set_smach_state(self, node_name, state):
        self.smach_states[node_name] = state

    def replace_node(self, new_smach_node, old_node_name):
        self.smach_states.pop(old_node_name)
        self.smach_states[new_smach_node.get_name()] = new_smach_node
        new_node_name = new_smach_node.get_name()

        #if the new node has the same name (possible to have different connections)
        #If the node is of a different name

        if new_node_name != old_node_name:
            self.gve.add_node(new_node_name, self.NODE_RADIUS)

        #for each existing connection
        new_outcomes = new_smach_node.get_registered_outcomes()
        for e in self.gve.node(old_node_name).edges:
        #   if it is an outcome in the new node
            if e.label in new_outcomes:
        #       if it has a different source, remove it and add a new one
                if e.node1.id == old_node_name:
                    self.gve.remove_edge(e.node1.id, e.node2.id, label=e.label)
                    self.gve.add_edge(new_node_name, e.node2.id, label=e.label, length=GraphModel.EDGE_LENGTH)
                elif e.node2.id == old_node_name:
                    self.gve.remove_edge(e.node1.id, e.node2.id, label=e.label)
                    self.gve.add_edge(e.node1.id, new_node_name, label=e.label, length=GraphModel.EDGE_LENGTH)
        #       if it has the same source ignore
        #   if it is not an outcome in our new node
            else:
                if e.node1.id == old_node_name:
                    print 'removing edge', e.node1.id, e.node2.id
                    self.gve.remove_edge(e.node1.id, e.node2.id, label=e.label)
                    if not self.is_modifiable(e.node2.id) and len(e.node2.edges) < 1:
                        self.gve.remove_node(e.node2.id)
                        self.smach_states.pop(e.node2.id)
                else:
                    self.gve.remove_edge(e.node1.id, e.node2.id, label=e.label)
                    self.gve.add_edge(e.node1.id, new_node_name, label=e.label, length=GraphModel.EDGE_LENGTH)
        #   delete it   

        if new_node_name != old_node_name:
            self.gve.remove_node(old_node_name)
                
        #for each new outcome
        #   if we don't have an edge for it, create that edge & its temporary node
        self.restore_node_consistency(new_smach_node.get_name())

        #if new_node_name != old_node_name:
        #    self.gve.add_node(new_node_name, radius=self.NODE_RADIUS)
        #    #remove edges to old node, add edges that point to the new node
        #    for e in self.gve.node(old_node_name).edges:
        #        self.gve.remove_edge(e.node1.id, e.node2.id, label=e.label)
        #        if e.node1.id == old_node_name:
        #            self.gve.add_edge(new_node_name, e.node2.id, label=e.label, length=GraphModel.EDGE_LENGTH)
        #        else:
        #            self.gve.add_edge(e.node1.id, new_node_name, label=e.label, length=GraphModel.EDGE_LENGTH)
        #    self.gve.remove_node(old_node_name)

    #def _outcome_name(self, node_name, outcome):
    #    return node_name + '_' + outcome

    def connectable_nodes(self, node_name, outcome):
        #can't connect to
        #  temporary nodes already connected whose name is not current outcome
        allowed_nodes = []
        #outcome_name = self._outcome_name(node_name, outcome)
        #allowed_nodes.append(outcome_name)
        for k in self.smach_states.keys():
            #If it's a temporary node and does not have the name of this outcome
            #if not self.is_modifiable(k) and k != outcome:
            if (not self.is_modifiable(k)) and (not self._is_type(k, outcome)):
                continue
            #ignore our own name
            if node_name == k:
                continue
            #ignore special global node
            if k == tu.InfoStateBase.GLOBAL_NAME:
                continue

            allowed_nodes.append(k)

        if node_name == None:
            allowed_nodes.append(self._create_outcome_name(outcome))
            allowed_nodes = list(set(allowed_nodes))

        return allowed_nodes

    ##
    # @return a list of nodes that are of subclass InfoStateBase
    def global_nodes(self, class_filter):
        allowed_nodes = []
        for k in self.smach_states.keys():
            state = self.smach_states[k]

            #Only use things of subclass tu.InfoStateBase
            if issubclass(state.__class__, tu.InfoStateBase):
                #Ignore global
                if k == tu.InfoStateBase.GLOBAL_NAME:
                    continue 

                #Only select objects of class given
                if class_filter != None and state.__class__ == class_filter:
                    allowed_nodes.append(k)
                else:
                    allowed_nodes.append(k)
        allowed_nodes.sort()
        return allowed_nodes

    def _create_outcome_name(self, outcome):
        idx = 0
        name = "%s%d" % (outcome, idx)
        while self.smach_states.has_key(name):
            idx = idx + 1
            name = "%s%d" % (outcome, idx)
        return name

    def _is_type(self, state_name, outcome):
        r = state_name.find(outcome)
        if r < 0:
            return False
        else:
            return True

    def add_node(self, smach_node):
        if self.smach_states.has_key(smach_node.name):
            raise RuntimeError('Already has node of the same name.  This case should not happen.')

        #if this is a regular singleton node
        if not hasattr(smach_node, 'get_child_name') or not self.smach_states.has_key(smach_node.get_child_name()):
            #Link this node to all its outcomes
            self.gve.add_node(smach_node.name, radius=self.NODE_RADIUS)
            self.smach_states[smach_node.name] = smach_node
            #print 'adding node', smach_node.name, 'with outcomes', smach_node.get_registered_outcomes()
            for outcome in smach_node.get_registered_outcomes():
                #print smach_node.name, outcome
                #outcome_name = self._outcome_name(smach_node.name, outcome)
                if outcome == tu.InfoStateBase.GLOBAL_NAME:
                    outcome_name = outcome
                else:
                    outcome_name = self._create_outcome_name(outcome)
                #if not self.smach_states.has_key(outcome):
                self.smach_states[outcome_name] = ot.EmptyState(outcome_name, temporary=True)
                self.gve.add_node(outcome_name, radius=self.NODE_RADIUS)
                #self.gve.add_edge(smach_node.name, outcome)
                self._add_edge(smach_node.name, outcome_name, outcome)
                #print '>>> adding edge between', smach_node.name, 'and', outcome_name, 'with label', outcome

        #If this node has a child node we replace its child node instead of performing an add
        else:
            self.replace_node(smach_node, smach_node.get_child_name())
            #self.restore_node_consistency(smach_node.name)

    def add_outcome(self, outcome_name):
        self.gve.add_node(outcome_name, radius=self.NODE_RADIUS)
        self.smach_states[outcome_name] = ot.EmptyState(outcome_name, False)

    def delete_node(self, node_name):
        node_obj = self.gve.node(node_name)
        children_edges = []
        parent_edges = []

        print 'deleting', node_name
        #Separate edges from parents and edges to children
        for cn in node_obj.links:
            for edge in self.gve.all_edges_between(node_name, cn.id):
                if (edge.node1.id == node_name) and (edge.node2.id == node_name):
                    raise Exception('Self link detected on node %s! This isn\'t supposed to happen.' % node_name)
                if edge.node1.id == node_name:
                    children_edges.append(edge)
                elif edge.node2.id == node_name:
                    parent_edges.append(edge)

        #Remove placeholder children nodes
        filtered_children_edges = []
        for e in children_edges:
            # If the connected node is not modifiable (i.e. a temporary added
            # node) and it doesn't have any other parents.
            #print 'child edge', e.label, e.node1.id, e.node2.id
            if not self.is_modifiable(e.node2.id) and len(e.node2.edges) <= 1:
                #print (not self.is_modifiable(e.node2.id)), (len(e.node2.edges) <= 1)
                #Delete it
                self.gve.remove_edge(node_name, e.node2.id, e.label)
                self.gve.remove_node(e.node2.id)
                self.smach_states.pop(e.node2.id)
            else:
                filtered_children_edges.append(e)

        #If we have one or more than one parent
        if len(parent_edges) >= 1:
            #Pick the first parent
            parent_node_id = parent_edges[0].node1.id
            parent_node = self.gve.node(parent_node_id)
            print 'picked parent', parent_node_id

            #Create an index of siblings
            parents_children = {}
            for parent_outcome_name, sibling_node_name in self.current_children_of(parent_node_id):
                parents_children[parent_outcome_name] = sibling_node_name
            print 'siblings', parents_children

            #For each child edge of ours
            for edge in filtered_children_edges:
                print 'processing child edge', edge.node1.id, edge.label, edge.node2.id
                #node_outcome_name = edge.outcome
                node_outcome_name = edge.label

                #if parent has a similar outcome connected to a temporary node
                if parents_children.has_key(node_outcome_name):
                    parent_outcome_node = parents_children[node_outcome_name]
                    #If parent outcome is connected to a temporary node, replace the temporary node with link to us
                    if not self.is_modifiable(parent_outcome_node):
                        #connect this child node to parent
                        self.gve.remove_edge(parent_node_id, parent_outcome_node, label=node_outcome_name)
                        self.gve.add_edge(parent_node_id, edge.node2.id, label=node_outcome_name, length=GraphModel.EDGE_LENGTH)
                        #e = self.gve.edge(parent_node_id, node_outcome_name)
                        #e.outcome = node_outcome_name
                        #delete parent's temporary node if it is now unconnected
                        if len(self.gve.node(parent_outcome_node).edges) < 1:
                            self.gve.remove_node(parent_outcome_node)
                            self.smach_states.pop(parent_outcome_node)
                #remove this edge
                self.gve.remove_edge(edge.node1.id, edge.node2.id, edge.label)

        #If no parents
        elif len(parent_edges) == 0:
            #just remove children edges
            for e in filtered_children_edges:
                self.gve.remove_edge(node_name, e.node2.id, label=e.label)

        #Remove edge from parents, and restore consistency for parent nodes
        for parent_edge in parent_edges:
            self.gve.remove_edge(parent_edge.node1.id, parent_edge.node2.id, parent_edge.label)
            self.restore_node_consistency(parent_edge.node1.id)

        self.gve.remove_node(node_name)
        self.smach_states.pop(node_name)
        if self.start_state == node_name:
            self.start_state = None

    # For each registered outcome, make sure there exists an edge.  If no
    # edge exists, create it.
    def restore_node_consistency(self, node_name):
        #print 'restoring consistency of node', node_name

        clist = self.current_children_of(node_name)
        cdict = {}
        #print 'outcomes that we have links for'
        for outcome_name, nn in clist:
            cdict[outcome_name] = nn
            #print outcome_name, nn

        print 'current children of', node_name, clist
        print 'registed outcomes are', self.smach_states[node_name].get_registered_outcomes()

        registered_outcomes = self.smach_states[node_name].get_registered_outcomes()

        #Remove things that are no longer outcomes
        for outcome in cdict.keys():
            if not (outcome in registered_outcomes):
                self.gve.remove_edge(node_name, cdict[outcome], outcome)
                if (not self.is_modifiable(cdict[outcome])) and len(self.gve.node(cdict[outcome]).edges) < 1:
                    self.gve.remove_node(cdict[outcome])
                    self.smach_states.pop(cdict[outcome])

        #print self.smach_states[node_name].__class__
        #print 'outcomes that we need', self.smach_states[node_name].get_registered_outcomes()

        for outcome in registered_outcomes:
            if not cdict.has_key(outcome):
                #print 'outcome', outcome, 'is missing. restoring connection'
                new_outcome_name = self._create_outcome_name(outcome)
                self._add_temporary_outcome(new_outcome_name)
                self._add_edge(node_name, new_outcome_name, outcome)

    def _add_temporary_outcome(self, outcome):
        self.smach_states[outcome] = ot.EmptyState(outcome, temporary=True)
        self.gve.add_node(outcome, self.NODE_RADIUS)

    #def delete_node_old(self, node_name):
    #    #temporary nodes are only removable when the state transitions are linked to something else
    #    if not self.is_modifiable(node_name):
    #        return 

    #    #Find parents and children
    #    node_obj = self.gve.node(node_name)
    #    children_edges = []
    #    parent_edges = []
    #    for cn in node_obj.links:
    #        edge = self.gve.edge(node_name, cn.id)
    #        if (edge.node1.id == node_name) and (edge.node2.id == node_name):
    #            raise Exception('Self link detected on node %s! This isn\'t supposed to happen.' % node_name)
    #        if edge.node1.id == node_name:
    #            children_edges.append(edge)
    #        elif edge.node2.id == node_name:
    #            parent_edges.append(edge)

    #    #Remove placeholder children nodes
    #    filtered_children_edges = []
    #    for e in children_edges:
    #        if not self.is_modifiable(e.node2.id) and len(e.node2.edges) <= 1:
    #            self.gve.remove_edge(node_name, e.node2.id)
    #            self.gve.remove_node(e.node2.id)
    #            self.smach_states.pop(e.node2.id)
    #        else:
    #            filtered_children_edges.append(e)

    #    new_selected_node = None
    #    #If we have one or more than one parent
    #    if len(parent_edges) >= 1:
    #        #Point edges on children to first parent
    #        parent_node_id = parent_edges[0].node1.id
    #        for e in filtered_children_edges:
    #            self.gve.remove_edge(node_name, e.node2.id)
    #            self.gve.add_edge(parent_node_id, e.node2.id)
    #        new_selected_node = parent_node_id

    #        #On each one of the parent, check to see if we are the terminal state
    #        for e in parent_edges:
    #            parent_id = e.node1.id
    #            outcome_set = set(self.get_smach_state(parent_id).get_registered_outcomes())
    #            if e.outcome in outcome_set:
    #                self.connection_changed(parent_id, e.outcome, e.outcome)
    #                #jjself.smach_states[e.outcome] = ot.EmptyState(e.outcome, temporary=True)
    #                #self.gve.add_node(e.outcome)
    #                #self._add_edge(parent_id, e.outcome, e.outcome)

    #    #If no parents
    #    elif len(parent_edges) == 0:
    #        #just remove children edges
    #        for e in filtered_children_edges:
    #            self.gve.remove_edge(node_name, e.node2.id)

    #        if len(filtered_children_edges) > 1:
    #            new_selected_node = filtered_children_edges[0].node2.id
    #        else:
    #            if len(self.gve.nodes) > 0:
    #                new_selected_node = self.gve.nodes[0].id
    #            else:
    #                new_selected_node = 'start'

    #    self.gve.remove_node(node_name)
    #    self.smach_states.pop(node_name)
    #    return new_selected_node

    def is_modifiable(self, node_name):
        if (self.smach_states[node_name].__class__ == ot.EmptyState) and self.smach_states[node_name].temporary:
            return False
        else:
            return True

    def _add_edge(self, n1, n2, n1_outcome):
        if not self.smach_states.has_key(n1) or not self.smach_states.has_key(n2):
            raise RuntimeError('One of the specified nodes does not exist.  Can\'t add edge.')

        if self.gve.edge(n1, n2, n1_outcome) != None:
            rospy.loginfo("Edge between %s and %s exists, ignoring connnection request" % (n1, n2))
            return False

        #Don't add edges to "temporary" nodes
        if n1_outcome == None and self.is_modifiable(n2):
            raise RuntimeError('Must specify outcome as goal node is not a temporary node.')

        self.gve.add_edge(n1, n2, label=n1_outcome, length=GraphModel.EDGE_LENGTH)
        #print 'actually added edge'
        #self.gve.edge(n1, n2).outcome = n1_outcome
        return True

    def add_edge(self, n1, n2, n1_outcome):
        if not self.is_modifiable(n1) or not self.is_modifiable(n2):
            return False
        else:
            return self._add_edge(n1, n2, n1_outcome)

    def delete_edge(self, edge):
        if not self.is_modifiable(edge.node1.id) or not self.is_modifiable(edge.node2.id):
            return False
        else:
            self.gve.remove_edge(edge.node1.id, edge.node2.id, e.label)
            return True

    def connection_changed(self, node_name, outcome_name, new_node):
        #node is not valid or hasn't been created yet

        if node_name == None:
            return

        if not self.smach_states.has_key(new_node):
            raise RuntimeError('Doesn\'t have state: %s' % new_node)
        #self.get_smach_state(node_name).outcome_choices[outcome_name] = new_node

        #find the old edge
        old_edge = None
        for edge in self.gve.node(node_name).edges:
            #if edge.outcome == outcome_name and edge.node1.id == node_name:
            #print 'edge', edge.node1.id, edge.node2.id, edge.label
            if edge.label == outcome_name and edge.node1.id == node_name:
                if old_edge != None:
                    raise RuntimeError('Two edges detected for one outcome named %s. %s -> %s and %s -> %s' % (outcome_name, old_edge.node1.id, old_edge.node2.id, edge.node1.id, edge.node2.id))
                old_edge = edge

        #print node_name, outcome_name, new_node
        if old_edge.node2.id == new_node:
            return

        #print 'connection_changed', node_name, outcome_name, new_node
        #remove the old connection
        self.gve.remove_edge(node_name, old_edge.node2.id, label=old_edge.label)
        #remove the old node if it's temporary 
        #print 'The old edge is named', old_edge.node2.id, not self.is_modifiable(old_edge.node2.id)
        if not self.is_modifiable(old_edge.node2.id):
            #and not connected
            #print 'it has this many edges', len(self.gve.node(old_edge.node2.id).edges)
            if len(self.gve.node(old_edge.node2.id).edges) <= 0:
                self.gve.remove_node(old_edge.node2.id)
                self.smach_states.pop(old_edge.node2.id)

        #add new connection
        if self.gve.node(new_node) == None:
            #print 'recreated node', new_node
            self.smach_states[new_node] = ot.EmptyState(new_node, temporary=True)
            self.gve.add_node(new_node, self.NODE_RADIUS)
        #print 'calling add_edge with a', node_name, 'b', new_node, 'outcome', outcome_name
        self._add_edge(node_name, new_node, outcome_name)

        #print 'THE KEYS ARE'
        #for k in self.smach_states.keys():
        #    print k

        #print 'OUR NEW EDGES ARE'
        #for e in self.gve.node(node_name).edges:
        #    print e.node1.id, e.node2.id, e.label

