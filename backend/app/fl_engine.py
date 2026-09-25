# backend/app/fl_engine.py
import os
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from app.encoders import encode_file


class SharedClassifier(nn.Module):
    def __init__(self, embedding_size=32, hidden_size=16):
        super().__init__()
        self.fc1 = nn.Linear(embedding_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, 1)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        return torch.sigmoid(self.fc2(x))


class FLEngine:
    def __init__(self):
        self.embedding_size = 32
        self.global_classifier = SharedClassifier(embedding_size=32)
        self.client_updates = {}
        self.round = 0
        self.model_dir = "data/global_model"
        os.makedirs(self.model_dir, exist_ok=True)

        path = os.path.join(self.model_dir, "classifier.pth")
        if os.path.exists(path):
            self.global_classifier.load_state_dict(torch.load(path))

    def get_global_classifier(self):
        return self.global_classifier.state_dict()

    def train_local(self, data_path: str, epochs: int = 5, lr: float = 0.01):
        encoded = encode_file(data_path, target_embedding_size=self.embedding_size)
        embeddings = torch.tensor(encoded["embedding"], dtype=torch.float32)
        labels = encoded["labels"]

        if labels is None:
            labels = torch.zeros(len(embeddings), 1)
        else:
            labels = torch.tensor(labels, dtype=torch.float32).view(-1, 1)

        classifier = SharedClassifier(embedding_size=self.embedding_size)
        classifier.load_state_dict(self.global_classifier.state_dict())

        opt = optim.Adam(classifier.parameters(), lr=lr)
        loss_fn = nn.BCELoss()

        # Optimize for Render Free Tier: Cap samples and increase batch size to prevent timeouts
        max_samples = 2048
        if len(embeddings) > max_samples:
            indices = torch.randperm(len(embeddings))[:max_samples]
            embeddings = embeddings[indices]
            labels = labels[indices]

        classifier.train()
        batch_size = 128
        for _ in range(epochs):
            for i in range(0, len(embeddings), batch_size):
                bx = embeddings[i:i + batch_size]
                by = labels[i:i + batch_size]
                opt.zero_grad()
                out = classifier(bx)
                loss = loss_fn(out, by)
                loss.backward()
                opt.step()

        classifier.eval()
        with torch.no_grad():
            preds = classifier(embeddings)
            predicted = (preds > 0.5).float()
            accuracy = (predicted == labels).float().mean().item()

        return {
            "weights": classifier.state_dict(),
            "accuracy": accuracy,
            "data_size": len(embeddings),
            "data_type": encoded["data_type"],
            "feature_count": encoded["feature_count"],
        }

    def add_differential_privacy(self, weights, epsilon=1.0):
        noisy = {}
        scale = 1.0 / epsilon
        for key, tensor in weights.items():
            noise = np.random.laplace(0, scale, tensor.shape)
            noisy[key] = tensor + torch.tensor(noise, dtype=torch.float32)
        return noisy

    def store_update(self, hospital_id, weights, data_size):
        self.client_updates[hospital_id] = (weights, data_size)

    def aggregate(self):
        if not self.client_updates:
            return {"round": self.round, "hospitals": 0}

        total = sum(size for _, size in self.client_updates.values())
        first_weights = next(iter(self.client_updates.values()))[0]
        avg = {key: torch.zeros_like(first_weights[key]) for key in first_weights}

        for hid, (weights, size) in self.client_updates.items():
            factor = size / total
            for key in weights:
                avg[key] += factor * weights[key]

        self.global_classifier.load_state_dict(avg)
        torch.save(avg, os.path.join(self.model_dir, "classifier.pth"))
        count = len(self.client_updates)
        self.client_updates = {}
        self.round += 1

        return {"round": self.round, "hospitals": count}

    def calculate_privacy_score(self, data_size, accuracy, epsilon=1.0):
        size_factor = min(data_size / 1000.0, 1.0)
        return min((1.0 / (1.0 + epsilon)) * size_factor, 1.0)