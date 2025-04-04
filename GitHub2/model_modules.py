{
 "cells": [
  {
   "cell_type": "code",
   "execution_count": 1,
   "id": "f66735c1",
   "metadata": {},
   "outputs": [
    {
     "name": "stderr",
     "output_type": "stream",
     "text": [
      "C:\\Users\\Malli\\anaconda3\\envs\\baceenv\\lib\\site-packages\\torch_geometric\\typing.py:86: UserWarning: An issue occurred while importing 'torch-scatter'. Disabling its usage. Stacktrace: [WinError 127] The specified procedure could not be found\n",
      "  warnings.warn(f\"An issue occurred while importing 'torch-scatter'. \"\n"
     ]
    }
   ],
   "source": [
    "import torch\n",
    "import torch.nn as nn\n",
    "import torch.nn.functional as F\n",
    "from torch_geometric.nn import GCNConv, global_mean_pool\n",
    "from torch_geometric.data import Data  # Add this import\n",
    "from typing import Tuple, List, Optional\n",
    "import copy\n",
    "from dataclasses import dataclass\n",
    "\n",
    "@dataclass\n",
    "class GanClConfig:\n",
    "    \"\"\"Configuration for GAN-CL training\"\"\"\n",
    "    node_dim: int\n",
    "    edge_dim: int\n",
    "    hidden_dim: int = 128\n",
    "    output_dim: int = 128\n",
    "    queue_size: int = 65536\n",
    "    momentum: float = 0.999\n",
    "    temperature: float = 0.07\n",
    "    decay: float = 0.99999\n",
    "    dropout_ratio: float = 0.25\n",
    "\n",
    "class MemoryQueue:\n",
    "    \"\"\"Memory queue with temporal decay for contrastive learning\"\"\"\n",
    "    def __init__(self, size: int, dim: int, decay: float = 0.99999):\n",
    "        self.size = size\n",
    "        self.dim = dim\n",
    "        self.decay = decay\n",
    "        self.ptr = 0\n",
    "        self.full = False\n",
    "        \n",
    "        # Initialize queue\n",
    "        self.queue = nn.Parameter(F.normalize(torch.randn(size, dim), dim=1), requires_grad=False)\n",
    "        self.queue_age = nn.Parameter(torch.zeros(size), requires_grad=False)\n",
    "        self.queue = F.normalize(self.queue, dim=1)\n",
    "        \n",
    "    def update_queue(self, keys: torch.Tensor):\n",
    "        \"\"\"Update queue with new keys\"\"\"\n",
    "        batch_size = keys.shape[0]\n",
    "        \n",
    "        # Increment age of all entries\n",
    "        self.queue_age += 1\n",
    "        \n",
    "        # Add new keys\n",
    "        if self.ptr + batch_size <= self.size:\n",
    "            self.queue[self.ptr:self.ptr + batch_size] = keys\n",
    "            self.queue_age[self.ptr:self.ptr + batch_size] = 0\n",
    "        else:\n",
    "            # Handle overflow\n",
    "            rem = self.size - self.ptr\n",
    "            self.queue[self.ptr:] = keys[:rem]\n",
    "            self.queue[:batch_size-rem] = keys[rem:]\n",
    "            self.queue_age[self.ptr:] = 0\n",
    "            self.queue_age[:batch_size-rem] = 0\n",
    "            self.full = True\n",
    "            \n",
    "        self.ptr = (self.ptr + batch_size) % self.size\n",
    "        \n",
    "    def get_decay_weights(self) -> torch.Tensor:\n",
    "        \"\"\"Get temporal decay weights for queue entries\"\"\"\n",
    "        return self.decay ** self.queue_age\n",
    "        \n",
    "    def compute_contrastive_loss(self, query: torch.Tensor, positive_key: torch.Tensor, \n",
    "                                temperature: float = 0.07) -> torch.Tensor:\n",
    "        \"\"\"Compute contrastive loss with temporal decay\"\"\"\n",
    "        # Normalize embeddings\n",
    "        query = F.normalize(query, dim=1)\n",
    "        positive_key = F.normalize(positive_key, dim=1)\n",
    "        queue = F.normalize(self.queue, dim=1)\n",
    "        \n",
    "        # Compute logits\n",
    "        l_pos = torch.einsum('nc,nc->n', [query, positive_key]).unsqueeze(-1)\n",
    "        l_neg = torch.einsum('nc,ck->nk', [query, queue.T])\n",
    "        \n",
    "        # Apply temporal decay to negative samples\n",
    "        decay_weights = self.get_decay_weights()\n",
    "        l_neg = l_neg * decay_weights.unsqueeze(0)\n",
    "        \n",
    "        # Temperature scaling\n",
    "        logits = torch.cat([l_pos, l_neg], dim=1) / temperature\n",
    "        labels = torch.zeros(logits.shape[0], dtype=torch.long, device=query.device)\n",
    "        \n",
    "        return F.cross_entropy(logits, labels)\n",
    "\n",
    "class GraphGenerator(nn.Module):\n",
    "    \"\"\"Generator network with proper feature handling\"\"\"\n",
    "    def __init__(self, node_dim: int, edge_dim: int, hidden_dim: int = 128):\n",
    "        super().__init__()\n",
    "        \n",
    "        # Node feature processing\n",
    "        self.node_encoder = nn.Sequential(\n",
    "            nn.Linear(node_dim, hidden_dim),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim, hidden_dim)\n",
    "        )\n",
    "        \n",
    "        # Edge feature processing\n",
    "        self.edge_encoder = nn.Sequential(\n",
    "            nn.Linear(edge_dim, hidden_dim),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim, hidden_dim)\n",
    "        )\n",
    "        \n",
    "        # Graph convolution layers\n",
    "        self.conv1 = GCNConv(hidden_dim, hidden_dim)\n",
    "        self.conv2 = GCNConv(hidden_dim, hidden_dim)\n",
    "        self.conv3 = GCNConv(hidden_dim, hidden_dim)\n",
    "        \n",
    "        # Importance prediction layers\n",
    "        self.node_importance = nn.Sequential(\n",
    "            nn.Linear(hidden_dim, hidden_dim // 2),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim // 2, 1),\n",
    "            nn.Sigmoid()\n",
    "        )\n",
    "        \n",
    "        self.edge_importance = nn.Sequential(\n",
    "            nn.Linear(hidden_dim * 2, hidden_dim),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim, 1),\n",
    "            nn.Sigmoid()\n",
    "        )\n",
    "        \n",
    "    def normalize_features(self, x_cat, x_phys):\n",
    "        \"\"\"Normalize categorical and physical features separately\"\"\"\n",
    "        # Convert categorical features to one-hot\n",
    "        x_cat = x_cat.float()\n",
    "        \n",
    "        # Normalize physical features\n",
    "        x_phys = x_phys.float()\n",
    "        if x_phys.size(0) > 1:  # Only normalize if we have more than one sample\n",
    "            x_phys = (x_phys - x_phys.mean(0)) / (x_phys.std(0) + 1e-5)\n",
    "            \n",
    "        return x_cat, x_phys\n",
    "        \n",
    "    def forward(self, data) -> Tuple[torch.Tensor, torch.Tensor]:\n",
    "        # Normalize features\n",
    "        x_cat, x_phys = self.normalize_features(data.x_cat, data.x_phys)\n",
    "        \n",
    "        # Concatenate features\n",
    "        x = torch.cat([x_cat, x_phys], dim=-1)\n",
    "        \n",
    "        edge_index = data.edge_index\n",
    "        edge_attr = data.edge_attr.float()  # Ensure float type\n",
    "        \n",
    "        # Initial feature encoding\n",
    "        x = self.node_encoder(x)\n",
    "        edge_attr = self.edge_encoder(edge_attr)\n",
    "        \n",
    "        # Graph convolutions\n",
    "        x = F.relu(self.conv1(x, edge_index))  # Removed edge_attr from GCNConv\n",
    "        x = F.relu(self.conv2(x, edge_index))\n",
    "        x = self.conv3(x, edge_index)\n",
    "        \n",
    "        # Predict importance scores\n",
    "        node_scores = self.node_importance(x)\n",
    "        \n",
    "        # Edge scores using both connected nodes\n",
    "        edge_features = torch.cat([\n",
    "            x[edge_index[0]], \n",
    "            x[edge_index[1]]\n",
    "        ], dim=-1)\n",
    "        edge_scores = self.edge_importance(edge_features)\n",
    "        \n",
    "        return node_scores, edge_scores\n",
    "\n",
    "class GraphDiscriminator(nn.Module):\n",
    "    \"\"\"Discriminator/Encoder network\"\"\"\n",
    "    def __init__(self, node_dim: int, edge_dim: int, hidden_dim: int = 128, output_dim: int = 128):\n",
    "        super().__init__()\n",
    "        \n",
    "        # Feature encoding\n",
    "        self.node_encoder = nn.Sequential(\n",
    "            nn.Linear(node_dim, hidden_dim),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim, hidden_dim)\n",
    "        )\n",
    "        \n",
    "        self.edge_encoder = nn.Sequential(\n",
    "            nn.Linear(edge_dim, hidden_dim),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim, hidden_dim)\n",
    "        )\n",
    "        \n",
    "        # Graph convolution layers\n",
    "        self.conv1 = GCNConv(hidden_dim, hidden_dim)\n",
    "        self.conv2 = GCNConv(hidden_dim, hidden_dim)\n",
    "        self.conv3 = GCNConv(hidden_dim, output_dim)\n",
    "        \n",
    "        # Projection head for contrastive learning\n",
    "        self.projection = nn.Sequential(\n",
    "            nn.Linear(output_dim, hidden_dim),\n",
    "            nn.ReLU(),\n",
    "            nn.Linear(hidden_dim, output_dim)\n",
    "        )\n",
    "        \n",
    "    def normalize_features(self, x_cat, x_phys):\n",
    "        \"\"\"Normalize categorical and physical features separately\"\"\"\n",
    "        # Convert categorical features to one-hot\n",
    "        x_cat = x_cat.float()\n",
    "        \n",
    "        # Normalize physical features\n",
    "        x_phys = x_phys.float()\n",
    "        if x_phys.size(0) > 1:  # Only normalize if we have more than one sample\n",
    "            x_phys = (x_phys - x_phys.mean(0)) / (x_phys.std(0) + 1e-5)\n",
    "            \n",
    "        return x_cat, x_phys \n",
    "        \n",
    "    def forward(self, data):\n",
    "        # Normalize features\n",
    "        x_cat, x_phys = self.normalize_features(data.x_cat, data.x_phys)\n",
    "        \n",
    "        # Concatenate features\n",
    "        x = torch.cat([x_cat, x_phys], dim=-1)\n",
    "        \n",
    "        edge_index = data.edge_index\n",
    "        edge_attr = data.edge_attr.float()  # Ensure float type\n",
    "        batch = data.batch if hasattr(data, 'batch') else None\n",
    "        \n",
    "        # Initial feature encoding\n",
    "        x = self.node_encoder(x)\n",
    "        edge_attr = self.edge_encoder(edge_attr)\n",
    "        \n",
    "        # Graph convolutions\n",
    "        x = F.relu(self.conv1(x, edge_index))  # Removed edge_attr from GCNConv\n",
    "        x = F.relu(self.conv2(x, edge_index))\n",
    "        x = self.conv3(x, edge_index)\n",
    "        \n",
    "        # Global pooling\n",
    "        if batch is not None:\n",
    "            x = global_mean_pool(x, batch)\n",
    "        else:\n",
    "            # If no batch information, treat as single graph\n",
    "            x = torch.mean(x, dim=0, keepdim=True)\n",
    "        \n",
    "        # Projection\n",
    "        x = self.projection(x)\n",
    "        \n",
    "        return x\n",
    "\n",
    "class MolecularGANCL(nn.Module):\n",
    "    \"\"\"Combined GAN and Contrastive Learning framework\"\"\"\n",
    "    def __init__(self, config: GanClConfig):\n",
    "        super().__init__()\n",
    "        self.config = config\n",
    "        \n",
    "        # Add weight initialization\n",
    "        def init_weights(m):\n",
    "            if isinstance(m, nn.Linear):\n",
    "                torch.nn.init.xavier_uniform_(m.weight)\n",
    "                m.bias.data.fill_(0.01)\n",
    "        \n",
    "        # Initialize networks\n",
    "        self.generator = GraphGenerator(\n",
    "            config.node_dim, \n",
    "            config.edge_dim, \n",
    "            config.hidden_dim * 2\n",
    "        )\n",
    "        \n",
    "        self.encoder = GraphDiscriminator(\n",
    "            config.node_dim,\n",
    "            config.edge_dim,\n",
    "            config.hidden_dim,\n",
    "            config.output_dim\n",
    "        )\n",
    "        self.encoder.apply(init_weights)\n",
    "        \n",
    "        # Modified loss weights\n",
    "        self.contrastive_weight = 1.0\n",
    "        self.adversarial_weight = 0.1\n",
    "        self.similarity_weight = 0.01\n",
    "        \n",
    "        # Temperature annealing\n",
    "        self.initial_temperature = 0.1\n",
    "        self.min_temperature = 0.05        \n",
    "        \n",
    "        # Create momentum encoder\n",
    "        self.momentum_encoder = copy.deepcopy(self.encoder)\n",
    "        for param in self.momentum_encoder.parameters():\n",
    "            param.requires_grad = False\n",
    "            \n",
    "        # Initialize memory queue\n",
    "        self.memory_queue = MemoryQueue(\n",
    "            config.queue_size,\n",
    "            config.output_dim,\n",
    "            config.decay\n",
    "        )\n",
    "        \n",
    "    @torch.no_grad()\n",
    "    def _momentum_update(self):\n",
    "        \"\"\"Update momentum encoder\"\"\"\n",
    "        for param_q, param_k in zip(self.encoder.parameters(), \n",
    "                                  self.momentum_encoder.parameters()):\n",
    "            param_k.data = self.config.momentum * param_k.data + \\\n",
    "                          (1 - self.config.momentum) * param_q.data\n",
    "                          \n",
    "    def drop_graph_elements(self, data, node_scores: torch.Tensor, \n",
    "                          edge_scores: torch.Tensor):\n",
    "        \"\"\"Apply dropout to graph based on importance scores\"\"\"\n",
    "        # Use random sampling with importance scores as probabilities\n",
    "        node_mask = (torch.rand_like(node_scores) > self.config.dropout_ratio).float()\n",
    "        edge_mask = (torch.rand_like(edge_scores) > self.config.dropout_ratio).float()\n",
    "\n",
    "        # Apply masks\n",
    "        x_cat_new = data.x_cat * node_mask\n",
    "        x_phys_new = data.x_phys * node_mask\n",
    "        edge_attr_new = data.edge_attr * edge_mask\n",
    "\n",
    "        # Create new graph data object\n",
    "        return Data(\n",
    "            x_cat=x_cat_new,\n",
    "            x_phys=x_phys_new,\n",
    "            edge_index=data.edge_index,\n",
    "            edge_attr=edge_attr_new,\n",
    "            batch=data.batch if hasattr(data, 'batch') else None,\n",
    "            num_nodes=data.num_nodes if hasattr(data, 'num_nodes') else None\n",
    "        )\n",
    "        \n",
    "    def get_temperature(self, epoch, total_epochs):\n",
    "        \"\"\"Anneal temperature during training\"\"\"\n",
    "        progress = epoch / total_epochs\n",
    "        return max(self.initial_temperature * (1 - progress), self.min_temperature)\n",
    "    \n",
    "    def forward(self, data, epoch=0, total_epochs=50):\n",
    "        # Get current temperature\n",
    "        temperature = self.get_temperature(epoch, total_epochs)\n",
    "        \n",
    "        # Get importance scores from generator\n",
    "        node_scores, edge_scores = self.generator(data)\n",
    "        \n",
    "        # Create perturbed graph\n",
    "        perturbed_data = self.drop_graph_elements(data, node_scores, edge_scores)\n",
    "        \n",
    "        # Get embeddings\n",
    "        query_emb = self.encoder(perturbed_data)\n",
    "        with torch.no_grad():\n",
    "            key_emb = self.momentum_encoder(data)\n",
    "            original_emb = self.encoder(data).detach()\n",
    "        \n",
    "        # Compute losses with modified weights\n",
    "        contrastive_loss = self.memory_queue.compute_contrastive_loss(\n",
    "            query_emb, key_emb, temperature\n",
    "        ) * self.contrastive_weight\n",
    "        \n",
    "        adversarial_loss = -F.mse_loss(query_emb, original_emb) * self.adversarial_weight\n",
    "        similarity_loss = F.mse_loss(query_emb, original_emb) * self.similarity_weight\n",
    "        \n",
    "        return contrastive_loss, adversarial_loss, similarity_loss\n",
    "    \n",
    "    def get_embeddings(self, data) -> torch.Tensor:\n",
    "        \"\"\"Get embeddings for downstream tasks\"\"\"\n",
    "        with torch.no_grad():\n",
    "            return self.encoder(data)"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3 (ipykernel)",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.9.21"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
