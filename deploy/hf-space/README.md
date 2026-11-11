---
title: MediFed API
emoji: 🏥
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Coordinator API of MediFed, a federated-learning research prototype
---

# MediFed coordinator API

The coordinator of MediFed, a research prototype of federated learning between hospitals. Hospitals train on
their own computers and send only model updates. The web app is deployed separately.

All data on this deployment is **SIMULATED** (fictional hospitals and records), labelled as such everywhere.
This is a research prototype, not a medical device. Federated learning reduces the need to centralise patient
data; it does not, by itself, guarantee privacy.

Source and documentation: https://github.com/kavya267-git/medi-fed (docs/deploy.md).
