// src/app/login/page.tsx — Login / Sign Up / Guest screen
'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';

type Tab = 'login' | 'signup' | 'guest';

export default function LoginPage() {
  const { login, signup, guestLogin } = useAuth();
  const { error } = useToast();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>('login');
  const [loading, setLoading] = useState(false);

  // Login form
  const [loginUser, setLoginUser] = useState('');
  const [loginPass, setLoginPass] = useState('');

  // Signup form
  const [signupUser, setSignupUser] = useState('');
  const [signupPass, setSignupPass] = useState('');
  const [signupName, setSignupName] = useState('');
  const [signupEmail, setSignupEmail] = useState('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(loginUser, loginPass);
      router.replace('/dashboard');
    } catch (err: unknown) {
      error((err as Error).message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await signup({
        username: signupUser,
        password: signupPass,
        full_name: signupName,
        email: signupEmail,
      });
      router.replace('/dashboard');
    } catch (err: unknown) {
      error((err as Error).message || 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  const handleGuest = async () => {
    setLoading(true);
    try {
      await guestLogin();
      router.replace('/dashboard');
    } catch (err: unknown) {
      error((err as Error).message || 'Guest login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-title">🏹 Fortress</div>
        <div className="login-subtitle">Professional quantitative dashboard & execution engine</div>

        <div className="tabs">
          <button className={`tab ${tab === 'login' ? 'active' : ''}`} onClick={() => setTab('login')}>
            🔐 Login
          </button>
          <button className={`tab ${tab === 'signup' ? 'active' : ''}`} onClick={() => setTab('signup')}>
            📝 Sign Up
          </button>
          <button className={`tab ${tab === 'guest' ? 'active' : ''}`} onClick={() => setTab('guest')}>
            👤 Guest
          </button>
        </div>

        {tab === 'login' && (
          <form onSubmit={handleLogin}>
            <div className="input-group" style={{ marginBottom: '16px' }}>
              <label>Username</label>
              <input className="input" value={loginUser} onChange={e => setLoginUser(e.target.value)} required />
            </div>
            <div className="input-group" style={{ marginBottom: '24px' }}>
              <label>Password</label>
              <input className="input" type="password" value={loginPass} onChange={e => setLoginPass(e.target.value)} required />
            </div>
            <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
              {loading ? <span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} /> : 'Sign In'}
            </button>
          </form>
        )}

        {tab === 'signup' && (
          <form onSubmit={handleSignup}>
            <div className="input-group" style={{ marginBottom: '12px' }}>
              <label>Username *</label>
              <input className="input" value={signupUser} onChange={e => setSignupUser(e.target.value)} required />
            </div>
            <div className="input-group" style={{ marginBottom: '12px' }}>
              <label>Full Name</label>
              <input className="input" value={signupName} onChange={e => setSignupName(e.target.value)} />
            </div>
            <div className="input-group" style={{ marginBottom: '12px' }}>
              <label>Email</label>
              <input className="input" type="email" value={signupEmail} onChange={e => setSignupEmail(e.target.value)} />
            </div>
            <div className="input-group" style={{ marginBottom: '24px' }}>
              <label>Password *</label>
              <input className="input" type="password" value={signupPass} onChange={e => setSignupPass(e.target.value)} required />
            </div>
            <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
              {loading ? <span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} /> : 'Create Account'}
            </button>
          </form>
        )}

        {tab === 'guest' && (
          <div>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', marginBottom: '24px', lineHeight: 1.6 }}>
              Explore the Fortress terminal with a temporary guest session.
              Note: Broker connections and order history are saved per account.
            </p>
            <button className="btn btn-secondary btn-block" onClick={handleGuest} disabled={loading}>
              {loading ? <span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} /> : 'Continue as Guest'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
