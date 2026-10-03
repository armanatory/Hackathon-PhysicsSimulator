# 🍺 Beer Cooling Simulator

A web application that simulates the transient cooling of beer in various environments using the Allsolve FEM platform.

## Overview

This application demonstrates how to:
- Build a complete simulation workflow with the Allsolve SDK
- Create parameterized thermal simulations
- Develop a modern web frontend with Vue 3
- Visualize simulation results in real-time

## Physics Model

The simulation solves the **transient heat conduction equation**:

```
ρ Cₚ ∂T/∂t = ∇ · (k ∇T)
```

With **convective boundary conditions**:

```
q = h (T_surface - T_coolant)
```

### Material Properties

| Property | Beer (Liquid) | Aluminum (Can) | Glass (Bottle) |
|----------|---------------|----------------|----------------|
| Density (kg/m³) | 1000 | 2700 | 2500 |
| Specific Heat (J/kg·K) | 4184 | 900 | 840 |
| Thermal Conductivity (W/m·K) | 1.2 | 237 | 1.0 |

### Cooling Methods

| Method | h_submerged (W/m²·K) | h_exposed (W/m²·K) | T_coolant (°C) |
|--------|----------------------|--------------------| ---------------|
| Ice Water | 600 | 10 | 0 |
| Refrigerator | 10 | 10 | 4 |
| Freezer | 15 | 15 | -18 |
| Salt & Ice | 800 | 10 | -5 |

## Project Structure

```
beer_cooling_app/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── allsolve/     # Allsolve SDK integration
│   │   ├── models/       # Pydantic models
│   │   ├── routers/      # API endpoints
│   │   ├── config.py     # Environment-based settings
│   │   └── main.py       # FastAPI application
│   ├── sim/
│   │   └── heat_transfer.py  # Quanscient simulation script
│   └── requirements.txt
├── frontend/             # Vue 3 frontend
│   ├── public/           # Static assets
│   ├── src/
│   │   ├── api/          # API client
│   │   ├── components/   # Vue components
│   │   ├── stores/       # Pinia state management
│   │   └── types/        # TypeScript type definitions
│   └── package.json
└── README.md
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Allsolve SDK credentials (for full simulations)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Allsolve SDK
pip install allsolve

# Set environment variables
export QS_ACCESS_KEY=your_key
export QS_SECRET_KEY=your_secret

# Run server
uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

### Access the Application

- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs

## Usage

1. **Select Container Type**: Choose between can, bottle, or pint glass
2. **Choose Cooling Method**: Ice water, refrigerator, freezer, or salt & ice
3. **Set Parameters**: Initial temperature, target temperature, immersion level
4. **Run Simulation**: Click "Start Cooling" to run the simulation
5. **View Results**: Watch the temperature curve and 3D visualization

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/simulation/start` | POST | Start a new simulation |
| `/api/simulation/{id}/status` | GET | Get simulation status |
| `/api/simulation/{id}/results` | GET | Get simulation results |
| `/api/simulation/{id}/abort` | POST | Abort a running simulation |
| `/api/simulation/{id}/demo` | POST | Run demo (no SDK required) |
| `/api/simulation/{id}/ws` | WS | WebSocket for real-time updates |

## Demo Mode

The application includes a demo mode that uses Newton's law of cooling for quick approximations without requiring the Allsolve backend. This is useful for testing the frontend.

## Credits

Built with:
- [Quanscient Allsolve](https://quanscient.com) - FEM simulation platform
- [Vue 3](https://vuejs.org) - Frontend framework
- [TresJS](https://tresjs.org) - Vue Three.js wrapper
- [FastAPI](https://fastapi.tiangolo.com) - Backend framework
- [Tailwind CSS](https://tailwindcss.com) - Styling

