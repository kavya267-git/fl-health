# backend/app/encoders.py
import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from PIL import Image


def detect_data_type(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".csv", ".tsv", ".xlsx"):
        return "ehr"
    if ext in (".npy", ".npz", ".wav", ".dat"):
        return "ecg"
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".dcm"):
        return "image"
    if ext in (".txt", ".json", ".md"):
        return "text"
    return "unknown"


class EHREncoder(nn.Module):
    def __init__(self, input_size, embedding_size=32):
        super().__init__()
        hidden = max(input_size, 64)
        self.net = nn.Sequential(
            nn.Linear(input_size, hidden),
            nn.ReLU(),
            nn.Linear(hidden, embedding_size),
            nn.ReLU(),
        )

    def forward(self, x):
        return self.net(x)


class ECGEncoder(nn.Module):
    def __init__(self, embedding_size=32, hidden_size=64):
        super().__init__()
        self.lstm = nn.LSTM(input_size=1, hidden_size=hidden_size,
                            num_layers=2, batch_first=True)
        self.fc = nn.Linear(hidden_size, embedding_size)

    def forward(self, x):
        out, (h, c) = self.lstm(x)
        return torch.relu(self.fc(h[-1]))


class ImageEncoder(nn.Module):
    def __init__(self, embedding_size=32):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(3, 16, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.fc = nn.Linear(64 * 4 * 4, embedding_size)

    def forward(self, x):
        h = self.conv(x)
        h = h.view(h.size(0), -1)
        return torch.relu(self.fc(h))


class TextEncoder:
    def __init__(self, embedding_size=32):
        self.embedding_size = embedding_size

    def encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.embedding_size, dtype=np.float32)
        for word in text.lower().split():
            idx = hash(word) % self.embedding_size
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec


def encode_file(filepath: str, target_embedding_size: int = 32):
    data_type = detect_data_type(filepath)

    if data_type == "ehr":
        df = pd.read_csv(filepath, header=None)
        n_features = df.shape[1] - 1
        last_col = df.iloc[:, -1]
        if last_col.nunique() <= 2:
            X = df.iloc[:, :-1].values.astype(np.float32)
            y = last_col.values.astype(np.float32)
        else:
            X = df.values.astype(np.float32)
            y = None

        X = np.nan_to_num(X)
        X_min, X_max = X.min(0, keepdims=True), X.max(0, keepdims=True)
        X = (X - X_min) / (X_max - X_min + 1e-8)

        encoder = EHREncoder(input_size=X.shape[1], embedding_size=target_embedding_size)
        encoder.eval()
        with torch.no_grad():
            emb = encoder(torch.tensor(X)).numpy()

        return {"embedding": emb, "labels": y, "data_type": "ehr", "feature_count": n_features}

    if data_type == "ecg":
        if filepath.endswith(".npy"):
            signal = np.load(filepath)
        elif filepath.endswith(".csv"):
            signal = pd.read_csv(filepath, header=None).values
        elif filepath.endswith(".wav"):
            import wave
            with wave.open(filepath, "rb") as w:
                signal = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        else:
            signal = np.fromfile(filepath, dtype=np.float32)

        signal = np.nan_to_num(signal).astype(np.float32)
        if signal.ndim == 1:
            signal = signal.reshape(1, -1)

        target_len = 1000
        resampled = np.zeros((signal.shape[0], target_len), dtype=np.float32)
        for i, row in enumerate(signal):
            idx = np.linspace(0, len(row) - 1, target_len).astype(int)
            resampled[i] = row[idx]

        resampled = (resampled - resampled.mean(1, keepdims=True)) / (resampled.std(1, keepdims=True) + 1e-8)

        encoder = ECGEncoder(embedding_size=target_embedding_size)
        encoder.eval()
        with torch.no_grad():
            x = torch.tensor(resampled).unsqueeze(-1)
            emb = encoder(x).numpy()

        return {"embedding": emb, "labels": None, "data_type": "ecg", "feature_count": resampled.shape[1]}

    if data_type == "image":
        img = Image.open(filepath).convert("RGB").resize((224, 224))
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))
        arr = np.expand_dims(arr, 0)

        encoder = ImageEncoder(embedding_size=target_embedding_size)
        encoder.eval()
        with torch.no_grad():
            emb = encoder(torch.tensor(arr)).numpy()

        return {"embedding": emb, "labels": None, "data_type": "image", "feature_count": 224 * 224 * 3}

    if data_type == "text":
        encoder = TextEncoder(embedding_size=target_embedding_size)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        emb = encoder.encode(text).reshape(1, -1)
        return {"embedding": emb, "labels": None, "data_type": "text", "feature_count": len(text.split())}

    raise ValueError(f"Unsupported data type: {data_type}")