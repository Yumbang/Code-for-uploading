"""
 This module, QMIX.py has been planned to only contain QMixer module. But at this time point(24/04/26), it is planned
to contain modules that is required by QMIX learning algorithm, including ReplayBuffer and RecurrentAgentNet.
 In the future, ultimately, the modules in this file will be separated into multiple modules and function as fundamentals
in multi-agent Q-learning, implemented role-based encoding or graph mix mixing algorithms.
"""
from TwoStageROProcessEnvironment.env.RecoveryControlledTwoStageROProcess import Transition
import sys
import numpy as np
sys.path.append(r'/home/ybang4/research/ROMARL')
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Linear, ReLU
from copy import copy, deepcopy

def mask_and_softmax(action_mask, Q):
    Q[action_mask == 0] = -torch.inf
    Q = F.softmax(Q, dim=0)
    return Q


def softmax_and_mask(action_mask, Q):
    Q = F.softmax(Q, dim=0)
    Q[action_mask == 0] = -torch.inf
    return Q

def mask_and_nothing(action_mask, Q):
    Q[action_mask == 0] = -torch.inf
    return Q

def centralized_mask_and_nothing(observation, Q):
    mask = []
    for i, a in enumerate(observation.keys()):
        mask.append(observation[a]['action_mask'])
    Q[0,mask[0] == 0,:,:] = -torch.inf
    Q[0,:,mask[1] == 0,:] = -torch.inf
    Q[0,:,:,mask[2] == 0] = -torch.inf
    return Q

def get_action_from_q(q_values, n_actions_list, batch_size):
    # Flatten the Q-values to find the max
    q_values_flat = q_values.view(batch_size, -1)  # Shape: (batch_size, total_joint_actions)
    max_q_values, max_indices = q_values_flat.max(dim=1)  # Shape: (batch_size,)

    # Convert flat indices back to action indices for each agent
    joint_action_indices = []
    for idx in max_indices:
        idx = idx.item()
        actions = []
        for n_actions in reversed(n_actions_list):
            actions.append(idx % n_actions)
            idx = idx // n_actions
        joint_action_indices.append(list(reversed(actions)))

    # joint_action_indices: List of lists, each containing the action indices for each agent
    return np.array(joint_action_indices).squeeze()

class QMixer(nn.Module):
    """
     QMixer class that takes individual action-value function of each agent and returns total action-value function.
     Constructed referring to QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent Reinforcement Learning
    (https://arxiv.org/abs/1803.11485v2)
    """

    def __init__(self, n_state_dim, n_agents, n_embedding_dim, device):
        """
         Initialize QMixer's attributes.
         Hypernetworks and mixing network parameters.
        :param n_state_dim: The number of state variable's features.
        :param n_agents: The number of agents. That is, the number of input layer's units of mixing network.
        :param n_embedding_dim: The number of units used for hidden layer of mixing network.
        """
        super(QMixer, self).__init__()

        self.n_state_dim = n_state_dim
        self.n_agents = n_agents
        self.n_embedding_dim = n_embedding_dim

        self.hyper_W1 = Linear(in_features=self.n_state_dim, out_features=self.n_agents * self.n_embedding_dim).to(device)
        self.hyper_W2 = Linear(in_features=self.n_state_dim, out_features=self.n_embedding_dim).to(device)
        self.hyper_b1 = nn.Sequential(
            Linear(in_features=self.n_state_dim, out_features=self.n_embedding_dim),
            ReLU()).to(device)
        self.hyper_b2 = nn.Sequential(
            Linear(in_features=self.n_state_dim, out_features=self.n_embedding_dim),
            ReLU(),
            Linear(in_features=self.n_embedding_dim, out_features=1)).to(device)

    def forward(self, agent_qs, state):
        """
         Evaluate Q_total with mixing network, generated by hypernetworks.
        :param agent_qs: Tensor(batch_size, n_agents, 1)
        :param state:  Tensor(batch_size, n_state_dim, 1)
        :return total_q: Tensor(batch_size, 1)
        """
        # Generate mixing network's parameters using hypernetworks.
        w1 = torch.abs(self.hyper_W1(state))        # w1: (batch_size, n_agents, n_embedding_dim)
        w1 = torch.reshape(w1, (-1, self.n_agents, self.n_embedding_dim))

        w2 = torch.abs(self.hyper_W2(state))        # w2: (batch_size, n_embedding_dim, 1)
        w2 = torch.reshape(w2, (-1, self.n_embedding_dim, 1))

        b1 = self.hyper_b1(state)                   # b1: (batch_size, n_embedding_dim, 1)
        b1 = torch.reshape(b1, (-1, 1, self.n_embedding_dim))

        b2 = self.hyper_b2(state)                   # b2: (batch_size, 1, 1)
        b2 = torch.reshape(b2, (-1, 1, 1))

        # Evaluate Q_total with mixing network.
        embedded = F.elu(torch.bmm(agent_qs, w1) + b1)  # embedded: (batch_size, n_embedding_dim)
        total_q = torch.bmm(embedded, w2) + b2          # total_q: (batch_size, 1)

        return total_q
    
class QMixerRevised(nn.Module):
    """
    QMixer class that takes individual action-value functions of each agent and returns the total action-value function.
    Constructed referring to QMIX: Monotonic Value Function Factorisation for Deep Multi-Agent Reinforcement Learning
    (https://arxiv.org/abs/1803.11485v2)
    """

    def __init__(self, n_state_dim, n_agents, n_embedding_dim, device):
        """
        Initialize QMixer's attributes.
        Hypernetworks and mixing network parameters.
        """
        super(QMixerRevised, self).__init__()

        self.n_state_dim = n_state_dim
        self.n_agents = n_agents
        self.n_embedding_dim = n_embedding_dim
        self.device = device

        # Hypernetworks for generating mixing network weights and biases
        self.hyper_W1 = nn.Linear(self.n_state_dim, self.n_agents * self.n_embedding_dim)
        self.hyper_W2 = nn.Linear(self.n_state_dim, self.n_embedding_dim)
        self.hyper_b1 = nn.Linear(self.n_state_dim, self.n_embedding_dim)
        self.V = nn.Sequential(
            nn.Linear(self.n_state_dim, self.n_embedding_dim),
            nn.ReLU(),
            nn.Linear(self.n_embedding_dim, 1)
        )

    def forward(self, agent_qs, state):
        """
        Evaluate Q_total with the mixing network, generated by hypernetworks.
        :param agent_qs: Tensor of shape (batch_size, n_agents)
        :param state: Tensor of shape (batch_size, n_state_dim)
        :return: total_q: Tensor of shape (batch_size, 1)
        """
        bs = agent_qs.size(0)
        agent_qs = agent_qs.view(-1, 1, self.n_agents)  # Shape: (batch_size, 1, n_agents)
        state = state.view(-1, self.n_state_dim)        # Shape: (batch_size, n_state_dim)

        # First layer
        w1 = torch.abs(self.hyper_W1(state))            # Shape: (batch_size, n_agents * n_embedding_dim)
        w1 = w1.view(-1, self.n_agents, self.n_embedding_dim)  # Shape: (batch_size, n_agents, n_embedding_dim)
        b1 = self.hyper_b1(state)                       # Shape: (batch_size, n_embedding_dim)
        b1 = b1.view(-1, 1, self.n_embedding_dim)       # Shape: (batch_size, 1, n_embedding_dim)

        # Compute hidden layer
        hidden = F.elu(torch.bmm(agent_qs, w1) + b1)    # Shape: (batch_size, 1, n_embedding_dim)

        # Second layer
        w2 = torch.abs(self.hyper_W2(state))            # Shape: (batch_size, n_embedding_dim)
        w2 = w2.view(-1, self.n_embedding_dim, 1)       # Shape: (batch_size, n_embedding_dim, 1)
        v = self.V(state).view(-1, 1, 1)                # Shape: (batch_size, 1, 1)

        # Compute total Q
        y = torch.bmm(hidden, w2) + v                   # Shape: (batch_size, 1, 1)
        total_q = y.view(bs, -1)                        # Shape: (batch_size, 1)

        return total_q
    
class VDN(nn.Module):
    def __init__(self):
        super(VDN, self).__init__()

    def forward(self, q):
        return torch.sum(q, dim=2, keepdim=False)


class ReplayBuffer:
    # TODO: Add descriptions.
    def __init__(self, agents):
        self.agents = agents
        self.memory = {}

    def push(self, transition: Transition):
        # Check if the episode_id from the transition is already a key in the memory dictionary
        episode_id = transition["episode_id"]-1

        if episode_id not in self.memory:
            # If not, initialize it with a list containing the current transition
            self.memory[episode_id] = [transition]
        else:
            # If it exists, append the current transition to the list associated with the episode_id
            self.memory[episode_id].append(transition)

    def sample(self, episode_id=None, include_last=False, return_whole=False) -> list[Transition]:
        # If no episode_id is provided, choose one randomly from the available keys
        if episode_id is None:
            if not self.memory:
                raise ValueError("Memory is empty. No episodes to sample.")
            episode_id = np.random.choice(list(self.memory.keys()))

        # Retrieve the list of transitions for the chosen episode_id
        transitions = self.memory.get(episode_id, [])

        if return_whole:
            return transitions

        # Check if there are enough transitions to sample the requested length
        if len(transitions) < self.batch_size:
            temp_batch_size = int(len(transitions) * 2/3)
            # raise ValueError(f"Not enough transitions in episode {episode_id} to sample {self.batch_size} elements.")
            # Choose the start index for sampling to ensure the sequence is continuous and of the desired length
            start_index = np.random.randint(0, len(transitions) - temp_batch_size + 1)

            # Return the sequential sample of transitions
            return transitions[start_index:start_index + temp_batch_size]

        temp_batch_size = np.max([self.batch_size, int(len(transitions) / 8)])
        if not include_last:
            # Choose the start index for sampling to ensure the sequence is continuous and of the desired length
            start_index = np.random.randint(0, len(transitions) - self.batch_size + 1)

            # Return the sequential sample of transitions
            return transitions[start_index:start_index + self.batch_size]
        else:
            # Return the sequential sample of transitions
            return transitions[-self.batch_size:]

    def give_advantage(self, episode_id, advantage):
        for transition in self.memory[episode_id]:
            transition = transition._replace(rewards=transition.rewards + advantage)



# Implementing Prioritized Experience Replay
# To decrease CPU-GPU communication overhead, stores data in GPU memory if available, and has a method to calculate loss over episodes.
class PrioritizedExperienceReplay(ReplayBuffer):
    def __init__(self, agents, device, mode = "BSU", prioritize=True, capacity=50000):
        super().__init__(agents)
        self.priority = {}
        self.isweights = {}
        self.td_error = {}
        self.device = device
        self.mode = mode  # BSU ("Bootstrapped sequential updates") or BRU ("Bootstrapped random updates"). Depreciated.
        self.do_prioritize = prioritize
        if self.device == "mps":
            torch.set_default_dtype(torch.float32)
        self.memory_cap = capacity
        self.episode_head = 0

    def to_device(self, transition, env):
        transition_copy = deepcopy(transition)
        previous_obs    = (transition_copy["previous_observations"])
        current_obs     = (transition_copy["observations"])
        previous_state  = (transition_copy["previous_state"])
        current_state   = (transition_copy["state"])
        rewards         = (transition_copy['rewards'])

        new_previous_obs    = {}
        new_current_obs     = {}
        previous_obs        = env.scale_observation(previous_obs)
        current_obs         = env.scale_observation(current_obs)
        for a in self.agents:
            new_previous_obs[a] = previous_obs[a]
            new_current_obs[a]  = current_obs[a]
            new_previous_obs[a]['observation'] = torch.from_numpy(previous_obs[a]['observation']).to(self.device)
            new_current_obs[a]['observation']  = torch.from_numpy(current_obs[a]['observation']).to(self.device)
        
        new_previous_state  = torch.reshape(torch.from_numpy(previous_state).float(),
                                                (1, -1)).to(self.device)
        new_current_state   = torch.reshape(torch.from_numpy(current_state).float(),
                                                (1, -1)).to(self.device)
        new_rewards         = torch.tensor(rewards).to(self.device)
        
        new_transition                          = deepcopy(transition)

        new_transition['previous_observations'] = new_previous_obs
        new_transition['observations']          = new_current_obs
        new_transition['previous_state']        = new_previous_state
        new_transition['state']                 = new_current_state
        new_transition['rewards']               = new_rewards

        return new_transition

    def push(self, transition, env):
        transition_transferred = self.to_device(transition, env)
        super().push(transition_transferred)
        self.priority[transition_transferred["episode_id"]-1] = 1

    def empty_head(self):
        # Empty the head of the memory. Called when the capacity is full.
        del self.memory[self.episode_head]
        del self.priority[self.episode_head]
        del self.isweights[self.episode_head]
        del self.td_error[self.episode_head]
        print(f"Deleted episode {self.episode_head} from memory.")
        self.episode_head += 1

    def calculate_loss(self, mixer, target_mixer, agent_nets:dict, target_agent_nets:dict, episode_id, device, env, gamma, weighted=True, reduction='mean'):
        # Method to calculate loss with the saved episodes. Has too many functionality and definitely needs refactoring. But it works.

        episode = self.memory[episode_id]

        if mixer is None:
            assert type(agent_nets) == CentralizedRNNAgent, "If mixer is None, agent network must be CentralizedRNNAgent."
            agent_hiddens = agent_nets.init_hidden()
            target_agent_hiddens = target_agent_nets.init_hidden()
            batch_agent_qs = torch.empty((0, 1, 1), device=device)
            batch_state = torch.empty((0, env.state().shape[0]), device=device)
            batch_target_qs = torch.empty((0, 1, 1), device=device)
            batch_previous_state = torch.empty((0, env.state().shape[0]), device=device)
        else:
            agent_hiddens = {a: agent_nets[a].init_hidden() for a in self.agents}
            target_agent_hiddens = {a: target_agent_nets[a].init_hidden() for a in self.agents}

            batch_agent_qs = torch.empty((0, 1, len(self.agents)), device=device)
            batch_state = torch.empty((0, env.state().shape[0]), device=device)
            batch_target_qs = torch.empty((0, 1, len(self.agents)), device=device)
            batch_previous_state = torch.empty((0, env.state().shape[0]), device=device)

        # _, _, _, _, _, zipped_rewards, _, _ = zip(*episode)
        zipped_rewards = [ep["rewards"] for ep in episode]
        batch_rewards = torch.tensor(zipped_rewards).to(device)

        # CTCE
        if mixer is None:
            for transition in episode:
                q, h          = agent_nets(transition["previous_state"], agent_hiddens)
                q             = centralized_mask_and_nothing(transition["previous_observations"], q)
                agent_qs      = q
                agent_hiddens = h

                with torch.no_grad():
                    target_q, target_h   = target_agent_nets(transition["state"], target_agent_hiddens)
                    target_q             = centralized_mask_and_nothing(transition["observations"], target_q)
                    target_agent_qs      = target_q
                    target_agent_hiddens = target_h

                tensor_agent_q         = torch.reshape(agent_qs[0,*transition['actions'].values()], (1,1,-1))
                tensor_previous_state  = torch.reshape(transition["previous_state"].float(), (1, -1))
                
                # DDQN
                cur_agent_qs    = {}
                cur_max_actions = {}
                q, _            = agent_nets(transition["state"], agent_hiddens)
                q               = centralized_mask_and_nothing(transition["observations"], q)
                cur_max_action  = get_action_from_q(q, n_actions_list=[5,5,5], batch_size=q.shape[0])

                tensor_target_q = torch.reshape(
                    target_agent_qs[0,*(cur_max_action)], (1, 1, -1)
                ).to(device)

                tensor_state = torch.reshape(transition["state"].to(device).float(), (1, -1)).to(device)

                batch_agent_qs          = torch.cat([batch_agent_qs, tensor_agent_q], dim=0).to(device)
                batch_state             = torch.cat([batch_state, tensor_state], dim=0).to(device)
                batch_target_qs         = torch.cat([batch_target_qs, tensor_target_q], dim=0).to(device)
                batch_previous_state    = torch.cat([batch_previous_state, tensor_previous_state], dim=0).to(device)

            total_q  = batch_agent_qs.squeeze()
            target_q = batch_target_qs.squeeze()

        
        # CTDE
        else:
            for transition in episode:
                agent_qs = {}
                target_agent_qs = {}
                if self.mode == "BRU":
                    agent_hiddens = {}

                for a in self.agents:
                    q, h        = agent_nets[a](transition["previous_observations"][a]['observation'], agent_hiddens[a])
                    q           = mask_and_nothing(action_mask=transition["previous_observations"][a]['action_mask'], Q=q)
                    agent_qs[a] = q
                    agent_hiddens[a] = h

                    with torch.no_grad():
                        target_q, target_h = target_agent_nets[a](transition["observations"][a]['observation'], target_agent_hiddens[a])
                        target_q    = mask_and_nothing(action_mask=transition["observations"][a]['action_mask'], Q=target_q)
                        target_agent_qs[a] = target_q
                        target_agent_hiddens[a] = target_h

                tensor_agent_qs        = torch.reshape(torch.stack([agent_qs[a][transition["actions"][a]] for a in self.agents]), (1, 1, -1)).to(device)
                tensor_previous_state  = torch.reshape(transition["previous_state"].float(), (1, -1))
                
                # DDQN
                cur_agent_qs = {}
                cur_max_actions = {}

                for a in self.agents:
                    q, _ = agent_nets[a](transition["observations"][a]['observation'], agent_hiddens[a])

                    q = mask_and_nothing(action_mask=transition["observations"][a]['action_mask'], Q=q)

                    cur_agent_qs[a] = q
                    cur_max_actions[a] = torch.argmax(q)

                tensor_target_qs = torch.reshape(
                    torch.stack([torch.gather(input=target_agent_qs[a], dim=0, index=cur_max_actions[a]) for a in self.agents]), (1, 1, -1)
                ).to(device)
                tensor_state = torch.reshape(transition["state"].to(device).float(), (1, -1)).to(device)

                batch_agent_qs          = torch.cat([batch_agent_qs, tensor_agent_qs], dim=0).to(device)
                batch_state             = torch.cat([batch_state, tensor_state], dim=0).to(device)
                batch_target_qs         = torch.cat([batch_target_qs, tensor_target_qs], dim=0).to(device)
                batch_previous_state    = torch.cat([batch_previous_state, tensor_previous_state], dim=0).to(device)
            
            if type(mixer) == QMixer or type(mixer) == QMixerRevised:
                total_q     = mixer(batch_agent_qs, batch_previous_state).squeeze()
                target_q    = target_mixer(batch_target_qs, batch_state).squeeze()
            elif type(mixer) == VDN:
                total_q     = mixer(batch_agent_qs).squeeze()
                target_q    = target_mixer(batch_target_qs).squeeze()


        discounted_reward = (batch_rewards.squeeze() + gamma * target_q.detach()).float().to(device)

        if weighted and type(mixer) == QMixer:
            # Weighted QMIX. Not used in the paper.
            alpha = 0.5  # Weight to use.
            td_error = total_q - discounted_reward.detach()
            ws = torch.ones_like(td_error) * alpha
            ws = torch.where(td_error < 0, torch.ones_like(td_error) * 1, ws)
            loss_raw = F.huber_loss(target=discounted_reward.detach(), input=total_q, reduction='none').float().to(device)
            loss = (ws.detach() * loss_raw).mean()
        else:
            loss = F.huber_loss(target=discounted_reward.detach(), input=total_q, reduction='mean').float().to(device)

        if torch.isinf(loss):
            pass  # Debug point.
        self.td_error[episode_id] = loss

    def calculate_batch_loss(self, mixer:QMixer, target_mixer:QMixer, agent_nets:dict, target_agent_nets:dict, episode_id, device, env, gamma, starting_index, batch_size, weighted=True):
        batch = self.memory[episode_id][starting_index: starting_index + batch_size]
        agent_hiddens = {a: agent_nets[a].init_hidden() for a in self.agents}

        target_agent_hiddens = {a: target_agent_nets[a].init_hidden() for a in self.agents}

        batch_agent_qs = torch.empty((0, 1, len(self.agents)), device=device)
        batch_state = torch.empty((0, env.state().shape[0]), device=device)
        batch_target_qs = torch.empty((0, 1, len(self.agents)), device=device)
        batch_previous_state = torch.empty((0, env.state().shape[0]), device=device)

        # _, _, _, _, _, zipped_rewards, _, _ = zip(*episode)
        zipped_rewards = [ep["rewards"] for ep in batch]
        batch_rewards = torch.tensor(zipped_rewards).to(device)

        for transition in batch:
            agent_qs = {}
            target_agent_qs = {}

            for a in self.agents:
                q, h = agent_nets[a](transition["previous_observations"][a]['observation'], agent_hiddens[a])

                target_q, target_h = target_agent_nets[a](transition["observations"][a]['observation'], target_agent_hiddens[a])

                q           = mask_and_nothing(action_mask=transition["previous_observations"][a]['action_mask'], Q=q)
                target_q    = mask_and_nothing(action_mask=transition["observations"][a]['action_mask'], Q=target_q)

                agent_qs[a] = q
                agent_hiddens[a] = h

                target_agent_qs[a] = target_q
                target_agent_hiddens[a] = target_h

            tensor_agent_qs        = torch.reshape(torch.stack([agent_qs[a][transition["actions"][a]] for a in self.agents]), (1, 1, -1)).to(device)
            tensor_previous_state  = torch.reshape(transition["previous_state"].float(), (1, -1))
            
            # DDQN
            cur_agent_qs = {}
            cur_max_actions = {}

            for a in self.agents:
                q, _ = agent_nets[a](transition["observations"][a]['observation'], agent_hiddens[a])

                q = mask_and_nothing(action_mask=transition["observations"][a]['action_mask'], Q=q)

                cur_max_actions[a] = torch.argmax(q)

            tensor_target_qs = torch.reshape(
                torch.stack([torch.gather(input=target_agent_qs[a], dim=0, index=torch.argmax(cur_max_actions[a])) for a in self.agents]), (1, 1, -1)
            ).to(device)
            tensor_state = torch.reshape(transition["state"].to(device).float(), (1, -1)).to(device)

            batch_agent_qs          = torch.cat([batch_agent_qs, tensor_agent_qs], dim=0).to(device)
            batch_state             = torch.cat([batch_state, tensor_state], dim=0).to(device)
            batch_target_qs         = torch.cat([batch_target_qs, tensor_target_qs], dim=0).to(device)
            batch_previous_state    = torch.cat([batch_previous_state, tensor_previous_state], dim=0).to(device)
        
        total_q     = mixer(batch_agent_qs, batch_previous_state).squeeze().float()
        target_q    = target_mixer(batch_target_qs, batch_state).squeeze().float()

        discounted_reward = (batch_rewards.squeeze() + gamma * target_q.detach()).float().to(device)

        # self.td_error[episode_id] = F.huber_loss(target=discounted_reward, input=total_q, reduction=reduction).float().to(device)
        return F.huber_loss(discounted_reward, total_q).float().to(device)
    
    def prioritize(self, mixer, target_mixer, agent_nets:dict, target_agent_nets:dict, device, env, gamma, mode, calculate_for_all = False):
        print("==== Prioritizing episodes ... ====")
        
        if mode == "UNIFORM":
            print("Uniform mode. Applying uniform priority across the episodes...")
        else:
            for episode_id in self.memory.keys():
                if calculate_for_all:
                    self.calculate_loss(mixer, target_mixer, agent_nets, target_agent_nets, episode_id, device, env, gamma)
                    print(f"| Calculate td error for episode {episode_id:<3} : {self.td_error[episode_id]:.2f} |")
        

        alpha = 0.7
        beta = 0.5

        # To prioritize episodes, use rank among episodes.
        if mode=="RANK-BASED":
            episode_rank = {}
            ranked_episode_td = dict(sorted(self.td_error.items(), key=lambda item: item[1], reverse=True))
            for rank, episode_id in enumerate(ranked_episode_td):
                episode_rank[episode_id] = rank + 1
            
            for episode_id, rank in episode_rank.items():
                if self.priority[episode_id] == 1:
                    self.priority[episode_id] == 1.0
                    # print(f"Episode {episode_id:<3}: New episode. Giving highest priority.")
                # elif self.td_error[episode_id] == 0:
                #     self.priority[episode_id] = 0.0
                #     continue
                else:
                    # print(f"Episode {episode_id:<3} : {rank}")
                    self.priority[episode_id] = np.power((1/(rank)), alpha)

            rank_powered_sum = np.sum(list(self.priority.values()))
            self.priority = {key: value / rank_powered_sum for key, value in self.priority.items()}
        elif mode=="PROPORTIONAL":
            self.priority = {key: torch.abs(value).detach().cpu() + 1e-5 for key, value in self.td_error.items()}
            priority_sum = np.sum(list(self.priority.values()))
            self.priority = {key: value / priority_sum for key, value in self.priority.items()}
        elif mode=="UNIFORM":
            self.priority = {key: 1 / len(self.memory) for key, _ in self.priority.items()}
        else:
            NotImplementedError("Prioritization mode of PER is not specified.")

        self.isweights = {key: np.power((1/len(self.memory))*(1/self.priority[key]), beta) for key, _ in self.priority.items()}
        # max_isweight = np.max(list(self.isweights.values()))
        # self.isweights = {key: value / max_isweight for key, value in self.priority.items()}


    def sample(self, episode_id):
        return self.td_error[episode_id], self.isweights[episode_id]
    
    def select_episodes(self, num_samples):
        episode_ids = list(self.memory.keys())
        priority_values = np.array([value for _, value in self.priority.items()])
        probabilities = priority_values / priority_values.sum()
        if num_samples > len(episode_ids):
            sampled_keys = episode_ids
        else:
            sampled_keys = np.random.choice(episode_ids, size=num_samples, p=probabilities, replace=False)
        sampled_keys = np.array(sampled_keys, dtype=np.int32)
        return sampled_keys


class RNNAgent(nn.Module):
    """
    RNN Agent code, copied from pymarl GitHub project. https://github.com/oxwhirl/pymarl/blob/master/src/modules/agents/rnn_agent.py
    """

    def __init__(self, input_shape, n_hidden_dim, n_actions):
        super(RNNAgent, self).__init__()

        self.n_hidden_dim = n_hidden_dim

        self.fc1 = nn.Linear(input_shape, n_hidden_dim)
        self.rnn = nn.GRUCell(n_hidden_dim, n_hidden_dim)
        self.fc2 = nn.Linear(n_hidden_dim, n_actions)

    def init_hidden(self):
        # make hidden states on same device as model
        return torch.zeros(1, self.n_hidden_dim, device=self.fc1.weight.device)

    def forward(self, inputs, hidden_state):
        x = F.relu(self.fc1(inputs))
        h_in = hidden_state.squeeze()
        # h_in = hidden_state
        h = self.rnn(x, h_in)
        q = self.fc2(h)
        return q, h
    
class CentralizedRNNAgent(nn.Module):
    def __init__(self, input_shape, n_hidden_dim, n_actions_list):
        super(CentralizedRNNAgent, self).__init__()
        self.n_hidden_dim = n_hidden_dim
        self.n_actions_list = n_actions_list  # List of action sizes for each agent

        # Calculate total number of joint actions
        self.total_joint_actions = 1
        for n_actions in n_actions_list:
            self.total_joint_actions *= n_actions

        # Input layer
        self.fc1 = nn.Linear(input_shape, n_hidden_dim)
        self.rnn = nn.GRUCell(n_hidden_dim, n_hidden_dim)
        # Output layer
        self.fc2 = nn.Linear(n_hidden_dim, self.total_joint_actions)

    def init_hidden(self, batch_size=1):
        # Initialize hidden states on the same device as the model
        return torch.zeros(batch_size, self.n_hidden_dim, device=self.fc1.weight.device)

    def forward(self, inputs, hidden_state):
        x = F.relu(self.fc1(inputs.squeeze()))
        h_in = hidden_state.squeeze()
        h = self.rnn(x, h_in)
        q_values = self.fc2(h)  # Shape: (batch_size, total_joint_actions)
        # Reshape to (batch_size, n_actions_agent1, n_actions_agent2, n_actions_agent3)
        q_values = q_values.view(-1, *self.n_actions_list)
        return q_values, h



if __name__ == '__main__':
    # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device = "cpu"
    batch_size = 8
    agent_qs = torch.rand((batch_size, 1, 5))
    state = torch.rand((batch_size, 8))
    qmixer = QMixer(n_agents=5, n_state_dim=8, n_embedding_dim=5, device=device).to(device)
    total_q = qmixer(agent_qs=agent_qs, state=state)
    print(f"Total Q : {total_q}")
