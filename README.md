# MediScanX: AI-Powered Multimodal Medical Scanner

  **By leveraging** **Edge AI**, the system enables the analysis of **ECG**, **Chest X-Rays**, and **Skin Lesions** directly on mid-range smartphones without requiring constant internet connectivity.

### 🌟 Key Features

* **Multimodal Diagnostic Engine:** Integrated support for Cardiovascular (ECG), Respiratory (CXR), and Dermatological (Skin) analysis.
* **Edge Inference:** Optimized models using **TFLite Post-Training Quantization** for sub-200ms on-device latency.
* **Explainable AI (XAI):** Generates **Grad-CAM++** heatmaps to visualize anatomical regions of interest, ensuring clinical transparency.
* **Intelligent Assistant (RAG):** A chatbot that retrieves context-aware medical insights from PubMed and WHO guidelines to explain results and mitigate AI hallucinations.
* **Digital Referral Bridge:** Generates cryptographically secure **Smart QR Reports** to facilitate patient transfer from rural BHUs to specialists.

---

## 🏗 Repository Structure

**Since you are catching up on architecture planning**, I recommend a **Monorepo** approach. This keeps your Flutter frontend, FastAPI backend, and ML training scripts in sync.

```
MediScanX/
├── mobile_app/                # Flutter Frontend (Target: Android) 
│   ├── assets/models/         # Exported .tflite files for Edge Inference
│   ├── lib/
│   │   ├── core/              # Encryption, QR generation, & Offline storage
│   │   ├── modules/           # Camera UI, Dashboard, and Chatbot interface 
│   │   └── services/          # API clients for FastAPI & Firebase 
│   └── test/                  # Usability testing scripts 
│
├── server_backend/            # FastAPI Cloud Layer 
│   ├── app/
│   │   ├── api/               # Endpoints for heavy processing & RAG
│   │   ├── rag_engine/        # FAISS vector DB & LangChain logic
│   │   └── database/          # SQLite/Firebase logic for history tracking 
│   └── knowledge_base/        # Indexed PubMed/WHO corpora
│
├── ml_research/               # Model Training & Optimization
│   ├── data_preprocessing/    # OpenCV, DullRazor scripts 
│   ├── notebooks/             # Jupyper notebooks for training baseline models 
│   ├── architectures/         # Enhanced Hybrid (CNN-BiLSTM) & MedLiteNet
│   └── quantization/          # Scripts for TFLite conversion & Grad-CAM++
│
├── docs/                      # FYP Proposals, Defense Presentations, & Ethics 
├── requirements.txt           # Python dependencies (PyTorch, TensorFlow, FastAPI)
└── README.md
```

---

## 🛠 Tech Stack

* **Frontend:** Flutter
* **Backend:** FastAPI (Python), SQLite/Firebase
* **ML/CV:** TensorFlow Lite (Mobile), PyTorch (Training), OpenCV
* **Explainability:** Grad-CAM++
* **Vector Store:** FAISS

---

## 📅 Roadmap & Progress

* **[x]** **EP1: Planning and Setup** (Ideation & Proposal)
* **[ ]** **EP2: 7th Sem Development** (In Progress: Dataset Access & Architecture)
* **[ ]** **EP3: 8th Sem Integration** (RAG & XAI Implementation)

---

## 👥 Contributors

* **Daud Noman**
* **Muhammad Arham Shafaat**
* **Wassam Khan**
* **Engr. Zubair Ahmad**
