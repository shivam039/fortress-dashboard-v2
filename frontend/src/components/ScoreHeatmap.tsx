// src/components/ScoreHeatmap.tsx
'use client';

import React from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';

export interface HeatmapData {
  Symbol: string;
  Score: number;
  Velocity: number;
  Position_Qty: number;
}

interface Props {
  data: HeatmapData[];
}

export default function ScoreHeatmap({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">📈</div>
        <p>No actionable picks to display on the heatmap.</p>
      </div>
    );
  }

  // Filter out invalid records
  const validData = data.filter(d => 
    typeof d.Score === 'number' && 
    typeof d.Velocity === 'number' && 
    typeof d.Position_Qty === 'number'
  );

  return (
    <div className="card">
      <h4 style={{ marginBottom: '16px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
        Conviction Heatmap (Score vs Velocity)
      </h4>
      <div style={{ width: '100%', height: '400px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
            <XAxis 
              type="number" 
              dataKey="Score" 
              name="Fortress Score" 
              stroke="var(--text-muted)"
              domain={[0, 100]}
              label={{ value: 'Fortress Score', position: 'bottom', fill: 'var(--text-muted)' }}
            />
            <YAxis 
              type="number" 
              dataKey="Velocity" 
              name="Velocity" 
              stroke="var(--text-muted)"
              label={{ value: 'Momentum Velocity', angle: -90, position: 'left', fill: 'var(--text-muted)' }}
            />
            <ZAxis 
              type="number" 
              dataKey="Position_Qty" 
              range={[100, 1000]} // Dot size mapping
              name="Position Size" 
            />
            <Tooltip 
              cursor={{ strokeDasharray: '3 3', stroke: 'var(--border-subtle)' }}
              contentStyle={{
                backgroundColor: 'var(--bg-card)',
                borderColor: 'var(--border-default)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)'
              }}
              labelFormatter={() => ''}
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const d = payload[0].payload;
                  return (
                    <div style={{ 
                      backgroundColor: 'var(--bg-card)', 
                      padding: '12px', 
                      border: '1px solid var(--border-default)',
                      borderRadius: 'var(--radius-md)'
                    }}>
                      <p style={{ fontWeight: 'bold', marginBottom: '8px' }}>{d.Symbol}</p>
                      <p style={{ fontSize: '0.8rem' }}>Score: {d.Score.toFixed(1)}</p>
                      <p style={{ fontSize: '0.8rem' }}>Velocity: {d.Velocity.toFixed(2)}</p>
                      <p style={{ fontSize: '0.8rem' }}>Suggested Qty: {d.Position_Qty}</p>
                    </div>
                  );
                }
                return null;
              }}
            />
            <Scatter data={validData}>
              {validData.map((entry, index) => (
                <Cell 
                  key={`cell-${index}`} 
                  fill={entry.Score >= 80 ? 'var(--color-success)' : entry.Score >= 60 ? 'var(--color-info)' : 'var(--color-warning)'} 
                  fillOpacity={0.7}
                />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
