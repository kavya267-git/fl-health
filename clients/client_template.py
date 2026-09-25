# clients/client_template.py
import requests
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

SERVER_URL = "http://localhost:8000"
HOSPITAL_EMAIL = "hospital@example.com"
HOSPITAL_PASSWORD = "your_password"
DATA_PATH = "data/hospitals/my_hospital/data.csv"


class DiseasePredictor(nn.Module):
    def __init__(self, input_size=13, hidden_size=64):
        super().__init__()
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.fc3 = nn.Linear(hidden_size, 1)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return torch.sigmoid(self.fc3(x))


def login():
    r = requests.post(f"{SERVER_URL}/api/auth/login", json={
        "email": HOSPITAL_EMAIL, "password": HOSPITAL_PASSWORD
    })
    r.raise_for_status()
    data = r.json()
    return data["access_token"], data["user"]["id"]


def train_local(data_path, epochs=5, lr=0.01):
    df = pd.read_csv(data_path, header=None)
    X = torch.tensor(df.iloc[:, :-1].values, dtype=torch.float32)
    y = torch.tensor(df.iloc[:, -1].values, dtype=torch.float32).view(-1, 1)

    model = DiseasePredictor()
    criterion = nn.BCELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    for _ in range(epochs):
        for i in range(0, len(X), 16):
            optimizer.zero_grad()
            out = model(X[i:i + 16])
            loss = criterion(out, y[i:i + 16])
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        acc = ((model(X) > 0.5).float() == y).float().mean().item()
    return acc


if __name__ == "__main__":
    token, user_id = login()
    print(f"Logged in as {user_id}")
    acc = train_local(DATA_PATH)
    print(f"Local training done. Accuracy: {acc * 100:.2f}%")
    r = requests.post(f"{SERVER_URL}/api/hospital/train", data={
        "hospital_id": user_id,
        "credential_hash": "PASTE_HASH_HERE",
        "epochs": 5,
        "epsilon": 1.0
    }, headers={"Authorization": f"Bearer {token}"})
    print(r.json())