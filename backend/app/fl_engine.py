# backend/app/fl_engine.py
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
import os

class DiseasePredictor(nn.Module):
    def __init__(self, input_size=13, hidden_size=64):
        super(DiseasePredictor, self).__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, 1)
    
    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return torch.sigmoid(self.fc3(x))


class FLEngine:
    def __init__(self, model_dir="data/global_model"):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        self.global_model = DiseasePredictor(13)
        self.round = 0
        self.model_path = os.path.join(model_dir, "global_model.pth")
        if os.path.exists(self.model_path):
            self.global_model.load_state_dict(torch.load(self.model_path))
    
    def get_global_model(self):
        return self.global_model.state_dict()
    
    def train_local(self, data_path, global_weights, epochs=5, lr=0.01):
        df = pd.read_csv(data_path, header=None)
        X = torch.tensor(df.iloc[:, :-1].values, dtype=torch.float32)
        y = torch.tensor(df.iloc[:, -1].values, dtype=torch.float32).view(-1, 1)
        
        model = DiseasePredictor(X.shape[1])
        model.load_state_dict(global_weights)
        
        criterion = nn.BCELoss()
        optimizer = optim.Adam(model.parameters(), lr=lr)
        
        model.train()
        for _ in range(epochs):
            for i in range(0, len(X), 16):
                optimizer.zero_grad()
                output = model(X[i:i+16])
                loss = criterion(output, y[i:i+16])
                loss.backward()
                optimizer.step()
        
        model.eval()
        with torch.no_grad():
            predictions = model(X)
            predicted = (predictions > 0.5).float()
            accuracy = (predicted == y).float().mean().item()
            loss_val = criterion(predictions, y).item()
        
        return {
            "weights": model.state_dict(),
            "accuracy": accuracy,
            "loss": loss_val,
            "data_size": len(df)
        }
    
    def add_differential_privacy(self, weights, epsilon=1.0):
        noisy = {}
        scale = 1.0 / epsilon
        for key, tensor in weights.items():
            noise = np.random.laplace(0, scale, tensor.shape)
            noisy[key] = tensor + torch.tensor(noise, dtype=torch.float32)
        return noisy
    
    def aggregate(self, client_updates, client_sizes):
        total = sum(client_sizes)
        avg = {}
        for key in client_updates[0].keys():
            avg[key] = torch.zeros_like(client_updates[0][key])
        for weights, size in zip(client_updates, client_sizes):
            w = size / total
            for key in weights:
                avg[key] += w * weights[key]
        self.global_model.load_state_dict(avg)
        self.round += 1
        torch.save(self.global_model.state_dict(), self.model_path)
        return self.global_model.state_dict()
    
    def calculate_privacy_score(self, data_size, accuracy, epsilon=1.0):
        size_score = min(data_size / 1000, 1.0)
        score = (1.0 / (1 + epsilon)) * size_score * accuracy
        return round(min(score, 1.0), 4)