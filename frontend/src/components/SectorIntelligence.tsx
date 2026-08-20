// src/components/SectorIntelligence.tsx
'use client';

import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

interface SectorPulse {
  Sector: string;
  Avg_Score: number;
  Velocity: number;
  Thesis?: string;
  Breadth?: number;
}

interface Props {
  data: SectorPulse[];
}

export default function SectorIntelligence({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">📊</div>
        <p>No sector intelligence available.</p>
      </div>
    );
  }

  // Sort by Avg_Score desc for charting
  const chartData = [...data].sort((a, b) => b.Avg_Score - a.Avg_Score);

  return (
    <div className="grid-2">
      <div className="card">
        <h4 style={{ marginBottom: '16px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
          Sector Strength (Avg Score)
        </h4>
        <div style={{ width: '100%', height: '300px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 5, right: 20, left: 20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" horizontal={true} vertical={false} />
              <XAxis type="number" domain={[0, 100]} stroke="var(--text-muted)" fontSize={12} />
              <YAxis 
                dataKey="Sector" 
                type="category" 
                stroke="var(--text-muted)" 
                fontSize={11}
                width={120}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--bg-card)',
                  borderColor: 'var(--border-default)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-primary)'
                }}
              />
              <Bar dataKey="Avg_Score" radius={[0, 4, 4, 0]}>
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={entry.Avg_Score >= 60 ? 'var(--color-success)' : entry.Avg_Score < 40 ? 'var(--color-danger)' : 'var(--color-warning)'} 
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      
      <div className="card">
        <h4 style={{ marginBottom: '16px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
          Sector Velocity
        </h4>
        <div style={{ width: '100%', height: '300px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 5, right: 20, left: 20, bottom: 25 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" vertical={false} />
              <XAxis 
                dataKey="Sector" 
                stroke="var(--text-muted)" 
                fontSize={11} 
                angle={-45}
                textAnchor="end"
              />
              <YAxis stroke="var(--text-muted)" fontSize={12} />
              <Tooltip
                contentStyle={{
                  backgroundColor: 'var(--bg-card)',
                  borderColor: 'var(--border-default)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-primary)'
                }}
              />
              <Bar dataKey="Velocity" radius={[4, 4, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-${index}`} 
                    fill={entry.Velocity > 0 ? 'var(--accent-primary)' : 'var(--color-danger)'} 
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
