# Start script for HA-MEEM AI Surveillance (Backend + Frontend)

Write-Host "Starting Ha-Meem AI Surveillance..." -ForegroundColor Cyan

# Check if port 8000 is already in use
$port8000 = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($port8000) {
    Write-Host "Warning: Port 8000 is already in use. Attempting to run anyway..." -ForegroundColor Yellow
}

# Start Backend
Write-Host "Launching Backend (FastAPI)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python run.py" -WindowStyle Normal

# Start Frontend
Write-Host "Launching Frontend (Vite)..." -ForegroundColor Green
if (Test-Path "frontend") {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev" -WindowStyle Normal
} else {
    Write-Host "Error: frontend directory not found!" -ForegroundColor Red
}

Write-Host "System is starting up." -ForegroundColor Cyan
Write-Host "Backend: http://localhost:8000"
Write-Host "Frontend: http://localhost:5173"
