# Remote Access Guide (using Cloudflared)

To show this application to your client on their PC without setting up complex port forwarding, you can use the `cloudflared-windows-amd64.exe` tool you already have.

### 1. Expose the Backend (Port 8000)
Run this command in your terminal:
```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:8000
```
Cloudflare will give you a random URL like `https://random-words.trycloudflare.com`. This URL will point to your local API.

### 2. Expose the Frontend (Port 5173)
In another terminal, run:
```powershell
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:5173
```
This will give you a second URL for the UI.

### Important: Update Frontend Config
If you use the tunnel for the backend, you must update `frontend/src/api/config.ts` to use that new Cloudflare URL so the browser can find the API from the client's PC.

```typescript
// frontend/src/api/config.ts
export const API_BASE_URL = "https://your-backend-tunnel.trycloudflare.com";
```

### Alternative: Local Network
If the client is on the same Wi-Fi/Office network, they can just go to:
`http://your-computer-ip:5173`
(Make sure your firewall allows traffic on 5173 and 8000).
