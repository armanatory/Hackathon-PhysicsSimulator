# Beer Cooling Simulation Backend

FastAPI backend for the beer cooling simulation application.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install the Allsolve SDK (from local wheel or pip):
```bash
pip install allsolve
```

4. Set environment variables:
```bash
export QS_ACCESS_KEY=your_access_key_here
export QS_SECRET_KEY=your_secret_key_here
export QS_HOST=https://allsolve.quanscient.com
```

## Running the Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### Start Simulation
```http
POST /api/simulation/start
Content-Type: application/json

{
  "container_shape": "can",
  "cooling_method": "ice_water",
  "initial_temp_celsius": 20.0,
  "target_temp_celsius": 4.0,
  "immersion_level": 0.8,
  "simulation_duration_minutes": 30
}
```

### Get Status
```http
GET /api/simulation/{simulation_id}/status
```

### Get Results
```http
GET /api/simulation/{simulation_id}/results
```

### Demo Mode (No SDK Required)
```http
POST /api/simulation/{simulation_id}/demo
Content-Type: application/json

{
  "container_shape": "can",
  "cooling_method": "ice_water",
  "initial_temp_celsius": 20.0
}
```

### WebSocket Updates
```
WS /api/simulation/{simulation_id}/ws
```

## Physics Model

The simulation solves the transient heat conduction equation:

**ρ Cₚ ∂T/∂t = ∇ · (k ∇T)**

With convective boundary conditions at the surface.

