# Citadel Dashboard — Production Runtime & Development Workflow

## 1. Runtime Modes

| Mode | Command | Port | LaunchAgent / Owner | Typical Memory Footprint | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DAILY_RUNTIME** (Production) | `npm run start` | `3000` | `com.citadel.frontend.plist` | **~64 MB** | Default live trading operation; pre-compiled static & SSR routes, zero compiler overhead. |
| **DEVELOPMENT_RUNTIME** | `npm run dev` | `3000` | Manual terminal | **~1.5 GB** | UI development, hot-reloading, live CSS/TSX iterations. |

---

## 2. Standard Daily Operation
The system launch daemon (`~/Library/LaunchAgents/com.citadel.frontend.plist`) automatically runs `npm run start` with `NODE_ENV=production`.

To check status:
```bash
launchctl list | grep citadel.frontend
```

---

## 3. UI Development Workflow (When Editing Frontend Code)

When intentionally coding or modifying components in `citadel-dashboard`:

1. **Temporarily stop the production daemon:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.citadel.frontend.plist
   ```

2. **Run the dev server with hot reload:**
   ```bash
   cd /Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/citadel-dashboard
   npm run dev
   ```

3. **When development is complete, build and resume production mode:**
   ```bash
   cd /Users/ayushmudgal/Developer/CitadelOS-Oracle-Post-E9/citadel-dashboard
   npm run build
   launchctl load ~/Library/LaunchAgents/com.citadel.frontend.plist
   ```

> [!IMPORTANT]
> Always execute `npm run build` after making UI code modifications so that production mode never serves stale assets.
