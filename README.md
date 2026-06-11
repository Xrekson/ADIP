# Auction Document Intelligence Pipeline

An end-to-end, async-first platform designed to automate the extraction of structured data from auction documents and stream real-time bidding and processing updates. 

This system decouples document ingestion from heavy machine learning processing using message queues, ensuring sub-second UI updates across concurrent auction sessions without blocking the main API thread.

---

## 🚀 Features

* **Automated Data Extraction:** Integrates Azure Document Intelligence to parse uploaded PDFs and scanned images, extracting structured data (lot numbers, item descriptions, estimated values, seller details) and reducing manual entry by ~80%.
* **Asynchronous Pipeline:** Utilizes Azure Service Bus to queue incoming documents. Background FastAPI workers consume these messages for reliable, non-blocking processing.
* **Real-Time Streaming:** Async WebSocket endpoints stream document processing statuses and live bid notifications directly to the frontend.
* **Role-Based Security:** JWT-based authentication adhering to OpenAPI 3.0 specifications, with strict access control for `Auctioneers`, `Bidders`, and `Admins`.
* **Reactive Frontend:** Built with Angular 19 and NgRx for highly reactive state management, styled with Tailwind CSS for a responsive user experience.

---

## 🛠️ Technology Stack

### Backend
* **Framework:** Python, FastAPI
* **Database:** PostgreSQL
* **Message Broker:** Azure Service Bus
* **AI/ML:** Azure Document Intelligence (Cognitive Services)
* **Real-time:** WebSockets

### Frontend
* **Framework:** Angular 19
* **State Management:** NgRx
* **Styling:** Tailwind CSS

### Infrastructure
* **Containerization:** Docker, Docker Compose

---

## 🏗️ Architecture Overview

1. **Upload:** An admin or auctioneer uploads an auction catalog (PDF/Image) via the Angular client.
2. **Ingestion:** The FastAPI backend receives the file, saves it to blob storage, and publishes a processing message to the **Azure Service Bus**.
3. **Background Processing:** A decoupled FastAPI worker picks up the message and sends the document to **Azure Document Intelligence**.
4. **Data Persistence:** The extracted structured data is validated and stored in **PostgreSQL**.
5. **Notification:** The worker broadcasts a "processing complete" event via **WebSockets**, instantly updating the Angular UI.

---

## 💻 Getting Started

### Prerequisites
* Python 3.10+
* Node.js 20+ & Angular CLI 19
* Docker & Docker Compose
* An active Azure account with Service Bus and Document Intelligence resources provisioned.

### 1. Clone the Repository
```bash
git clone [https://github.com/yourusername/e-auction-document-pipeline.git](https://github.com/yourusername/e-auction-document-pipeline.git)
cd e-auction-document-pipeline