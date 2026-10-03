# Beer Cooling Simulator Frontend

A Vue 3 application for visualizing beer cooling simulations.

## Tech Stack

- **Vue 3** with Composition API
- **TypeScript** for type safety
- **Pinia** for state management
- **TresJS** for 3D visualization (Three.js wrapper)
- **Chart.js + vue-chartjs** for temperature charts
- **Tailwind CSS** for styling
- **Vite** for development and building

## Setup

1. Install dependencies:
```bash
npm install
```

2. Start development server:
```bash
npm run dev
```

The app will be available at http://localhost:5173

## Features

- **Interactive 3D View**: Visualize the beer can/bottle in the cooling environment
- **Parameter Controls**: Adjust container type, cooling method, temperatures, and immersion level
- **Real-time Charts**: Watch the temperature decrease over time
- **Playback Controls**: Replay the simulation at any speed
- **Demo Mode**: Quick approximations without backend (Newton's law of cooling)
- **Full Simulation**: Connect to Allsolve backend for accurate FEM results

## Project Structure

```
src/
├── api/                 # API client for backend
├── assets/              # CSS and static assets
├── components/          # Vue components
│   ├── GeometryViewer.vue    # 3D visualization
│   ├── ParameterPanel.vue    # Input controls
│   ├── ResultsChart.vue      # Temperature chart
│   └── TemperatureDisplay.vue # Current temp display
├── stores/              # Pinia stores
│   └── simulationStore.ts
├── types/               # TypeScript type definitions
├── App.vue              # Root component
└── main.ts              # Application entry
```

## Development

### Build for production
```bash
npm run build
```

### Preview production build
```bash
npm run preview
```

## Configuration

The frontend proxies API requests to `http://localhost:8000` during development.
Update `vite.config.ts` to change the backend URL.

