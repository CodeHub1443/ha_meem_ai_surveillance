# Ha-meem Front-End | TDI Surveillance System

![TDI Surveillance Banner](https://img.shields.io/badge/Surveillance-AI--Powered-blueviolet?style=for-the-badge&logo=shippable)
![Tech Stack](https://img.shields.io/badge/Tech_Stack-TanStack_Start_%2B_React-61DAFB?style=for-the-badge&logo=react)
![Tailwind CSS](https://img.shields.io/badge/Styling-Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css)

A high-performance, real-time surveillance dashboard designed for the Ha-meem Industrial Group. This application serves as the command center for the **TDI AI-Powered Face Recognition System**, providing deep insights into security events, personnel tracking, and camera management.

---

## 🚀 Key Features

### 📊 Intelligence Dashboard
*   **Real-time Analytics**: Monitor total events, unauthorized detections, and active camera status at a glance.
*   **Dynamic Charts**: Visualize event breakdowns (Authorized vs. Unknown) over time using Recharts.
*   **Live Alerts**: Instant notification system for unauthorized person detections.

### 🎥 Live View & Monitoring
*   **Low-Latency Streams**: Integrated camera views with seamless switching.
*   **Event Overlay**: See the latest recognition results directly alongside the live feed.
*   **ROI Drawing**: Interactive canvas to define custom **Regions of Interest (ROI)** for specialized monitoring zones.

### 📋 Advanced Reporting
*   **Comprehensive Filtering**: Filter security events by camera, date range, and identity type.
*   **Export Capabilities**: One-click **CSV Export** for security audits and reporting.
*   **Enrolled Directory**: View and manage all personnel registered in the recognition gallery with accuracy statistics.

### 🔐 Security & Access
*   **Lock Screen**: Protected entry with PIN-based authentication.
*   **Session Management**: Secure session handling for industrial environment stability.

---

## 🛠️ Tech Stack

-   **Framework**: [TanStack Start](https://tanstack.com/start) (Full-stack React with Vite)
-   **Routing**: [TanStack Router](https://tanstack.com/router)
-   **State Management**: [TanStack Query](https://tanstack.com/query) (for async data & caching)
-   **Styling**: [Tailwind CSS](https://tailwindcss.com/) with [Shadcn UI](https://ui.shadcn.com/) components
-   **Icons**: [Lucide React](https://lucide.dev/)
-   **Internationalization**: `i18next` (Supports English & Bengali)
-   **Date Handling**: `date-fns`

---

## ⚙️ Configuration

The application uses environment variables for security and API connectivity. Create a `.env` file in the root directory:

```env
VITE_UNLOCK_PIN=1234
VITE_API_BASE_URL=http://your-surveillance-api-ip:5000
```

---

## 🏗️ Getting Started

### Prerequisites
*   [Bun](https://bun.sh/) (Recommended) or [Node.js](https://nodejs.org/) (v18+)

### Installation
```bash
# Clone the repository
git clone https://github.com/CodeHub1443/Ha-Meem-Front-End.git

# Navigate to the directory
cd vigil-vision-app

# Install dependencies
bun install
# or
npm install
```

### Development
```bash
bun dev
# or
npm run dev
```

### Build
```bash
bun run build
# or
npm run build
```

---

## 🌐 Localization
The system is fully localized to support regional operations:
*   **English**: Default international interface.
*   **Bengali**: Native language support for local operators.

---

## 🛡️ License
Proprietary - Developed for **Ha-meem Industrial Group**.

---

*Developed by CodeHub1443*
