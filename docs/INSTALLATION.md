# Installation Guide

## Prerequisites
- Docker Engine 24.0+
- Docker Compose v2.20+
- Git 2.40+

## Quick Automated Installation

### Linux / macOS
```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

### Windows (PowerShell)
```powershell
.\bootstrap.ps1
```

## Manual Step-by-Step Installation
1. Clone repository and vendor dependencies:
   ```bash
   make configure
   ```
2. Build container images:
   ```bash
   make build
   ```
3. Start core profile services:
   ```bash
   make up
   ```
4. Check health status:
   ```bash
   make health
   ```
