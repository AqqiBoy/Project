import React, { useEffect, useRef, useState } from 'react';
import { Terminal as TerminalIcon, Play, Square, Plus, Trash2, Server, Users, Send, Activity, Monitor } from 'lucide-react';
import clsx from 'clsx';

// --- API CLIENT ---
const API_URL = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000/ws/logs";

async function apiCall(endpoint, method = 'POST', body = null) {
  try {
    const opts = { method };
    if (body) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(`${API_URL}${endpoint}`, opts);
    return await res.json();
  } catch (e) {
    console.error(e);
    return { success: false, error: e.message };
  }
}

// --- COMPONENTS ---

const Button = ({ onClick, children, variant = 'primary', disabled, className, size = 'md' }) => {
  const base = "rounded font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed";
  
  const sizes = {
    sm: "px-2 py-1 text-xs",
    md: "px-3 py-1.5 text-sm",
    icon: "p-1.5"
  };

  const variants = {
    primary: "bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border border-blue-500/20",
    success: "bg-green-500/10 text-green-400 hover:bg-green-500/20 border border-green-500/20",
    danger: "bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/20",
    neutral: "bg-white/5 text-gray-300 hover:bg-white/10 border border-white/10"
  };
  
  return (
    <button onClick={onClick} disabled={disabled} className={clsx(base, variants[variant], sizes[size], className)}>
      {children}
    </button>
  );
};

const StatusDot = ({ active, pulse }) => (
  <div className="relative flex h-2.5 w-2.5">
    {active && pulse && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>}
    <span className={clsx("relative inline-flex rounded-full h-2.5 w-2.5", active ? "bg-green-500" : "bg-red-500/50")}></span>
  </div>
);

const Terminal = ({ logs }) => {
  const endRef = useRef(null);
  
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="flex-1 bg-black/50 rounded border border-border font-mono text-[11px] p-3 overflow-y-auto h-full leading-relaxed shadow-inner">
      {logs.length === 0 && <span className="text-gray-600 italic">Waiting for system logs...</span>}
      {logs.map((log, i) => {
        let color = "text-gray-300";
        if (log.includes("[System]")) color = "text-yellow-400 font-bold";
        else if (log.includes("[LoadBalancer]")) color = "text-blue-400";
        else if (log.includes("Client")) color = "text-green-400";
        else if (log.includes("B")) color = "text-purple-400";
        
        // Highlight logic
        if (log.includes("healthy") || log.includes("Accepted")) color += " bg-green-500/10";
        if (log.includes("unhealthy") || log.includes("Error")) color += " bg-red-500/10";

        return (
          <div key={i} className={clsx("break-words border-b border-white/5 py-0.5", color)}>
             <span className="opacity-50 mr-2 text-[10px]">{new Date().toLocaleTimeString().split(' ')[0]}</span>
             {log}
          </div>
        )
      })}
      <div ref={endRef} />
    </div>
  );
};

// --- MAIN APP ---

function App() {
  const [logs, setLogs] = useState([]);
  const [state, setState] = useState({ load_balancer: 'stopped', servers: [], clients: [] });
  const [selectedClient, setSelectedClient] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  // WebSocket
  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    ws.onmessage = (event) => setLogs(prev => [...prev.slice(-2000), event.data]);
    return () => ws.close();
  }, []);

  // Polling State
  const fetchState = async () => {
    const data = await apiCall('/api/state', 'GET');
    setState(data);
  };

  useEffect(() => {
    fetchState();
    const interval = setInterval(fetchState, 1000);
    return () => clearInterval(interval);
  }, []); // Run continuously

  // Auto-select client ONLY if we have clients but none selected
  useEffect(() => {
    if (!selectedClient && state.clients.length > 0) {
      setSelectedClient(state.clients[0].id);
    }
  }, [state.clients, selectedClient]);

  // Handlers
  const toggleLB = async () => {
    setLoading(true);
    if (state.load_balancer === 'running') await apiCall('/api/lb/stop');
    else await apiCall('/api/lb/start');
    await fetchState();
    setLoading(false);
  };

  const addServer = async () => {
    await apiCall('/api/server/add');
    fetchState();
  };

  const toggleServer = async (name, status) => {
    if (status === 'running') await apiCall(`/api/server/${name}/stop`);
    else await apiCall(`/api/server/${name}/start`);
    fetchState();
  };

  const removeServer = async (name) => {
    if (!confirm(`Remove server ${name}?`)) return;
    await apiCall(`/api/server/${name}`, 'DELETE');
    fetchState();
  };

  const addClient = async () => {
    const res = await apiCall('/api/client/add');
    if (res.success) {
       setSelectedClient(res.id);
       fetchState();
    }
  };

  const removeClient = async (id) => {
    await apiCall(`/api/client/${id}`, 'DELETE');
    if (selectedClient === id) setSelectedClient("");
    fetchState();
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!message || !selectedClient) return;
    await apiCall('/api/client/send', 'POST', { client_id: selectedClient, message });
    setMessage("");
  };

  return (
    <div className="h-screen bg-background text-gray-200 font-sans overflow-hidden flex flex-col">
      {/* HEADER */}
      <header className="h-14 border-b border-border bg-surface px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Activity className="text-blue-500" />
          <h1 className="font-bold text-lg tracking-tight">LoadBalancer<span className="text-gray-500">Lab</span></h1>
        </div>
        <div className="flex items-center gap-4 text-xs font-mono">
           <div className="flex items-center gap-2 px-3 py-1 bg-black/20 rounded border border-white/5">
             <StatusDot active={state.load_balancer === 'running'} pulse />
             <span>Load Balancer: {state.load_balancer.toUpperCase()}</span>
           </div>
        </div>
      </header>

      {/* MAIN CONTENT */}
      <div className="flex-1 flex overflow-hidden">
        
        {/* COL 1: INFRASTRUCTURE */}
        <div className="w-80 border-r border-border bg-black/10 flex flex-col">
          <div className="p-4 border-b border-border bg-surface/50">
             <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-2">
                <Server size={14} /> Core System
             </h2>
             <div className="flex items-center justify-between p-3 bg-blue-500/5 border border-blue-500/10 rounded-lg">
                <div className="flex flex-col">
                   <span className="text-sm font-bold text-blue-400">Load Balancer</span>
                   <span className="text-[10px] text-gray-500">Port 8080</span>
                </div>
                <Button 
                   size="sm" 
                   variant={state.load_balancer === 'running' ? 'danger' : 'success'}
                   onClick={toggleLB}
                   disabled={loading}
                >
                   {state.load_balancer === 'running' ? <Square size={12}/> : <Play size={12}/>}
                   {state.load_balancer === 'running' ? 'Stop' : 'Start'}
                </Button>
             </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
             <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Backend Servers</h2>
                <Button size="sm" variant="neutral" onClick={addServer} className="!p-1"><Plus size={14}/></Button>
             </div>
             
             <div className="space-y-2">
                {state.servers.map(s => (
                   <div key={s.name} className="p-2 rounded border border-white/5 bg-surface hover:border-white/10 transition-colors group">
                      <div className="flex items-center justify-between mb-2">
                         <div className="flex items-center gap-2">
                            <StatusDot active={s.status === 'running'} />
                            <span className="text-sm font-mono font-bold">{s.name}</span>
                            <span className="text-[10px] text-gray-500 bg-white/5 px-1 rounded">:{s.port}</span>
                         </div>
                         <button onClick={() => removeServer(s.name)} className="text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">
                            <Trash2 size={12} />
                         </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                         <Button 
                            size="sm" 
                            variant="success" 
                            disabled={s.status === 'running'}
                            onClick={() => toggleServer(s.name, s.status)}
                            className="!py-0.5 text-[10px]"
                         >
                            Start
                         </Button>
                         <Button 
                            size="sm" 
                            variant="danger" 
                            disabled={s.status === 'stopped'}
                            onClick={() => toggleServer(s.name, s.status)}
                            className="!py-0.5 text-[10px]"
                         >
                            Stop
                         </Button>
                      </div>
                   </div>
                ))}
             </div>
          </div>
        </div>

        {/* COL 2: CLIENTS & SIMULATION */}
        <div className="w-96 border-r border-border bg-surface/30 flex flex-col">
          <div className="p-4 border-b border-border">
             <div className="flex items-center justify-between mb-4">
                <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                   <Users size={14} /> Active Clients
                </h2>
                <Button size="sm" variant="neutral" onClick={addClient} disabled={state.load_balancer !== 'running'}>
                   <Plus size={12} /> Add Client
                </Button>
             </div>
             
             {state.load_balancer !== 'running' && (
                <div className="p-3 bg-yellow-500/10 border border-yellow-500/20 rounded text-xs text-yellow-500 mb-4">
                   ⚠️ Start Load Balancer to connect clients.
                </div>
             )}

             <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin">
                {state.clients.map(c => (
                   <button 
                      key={c.id}
                      onClick={() => setSelectedClient(c.id)}
                      className={clsx(
                         "flex items-center gap-2 px-3 py-1.5 rounded border text-xs whitespace-nowrap transition-colors",
                         selectedClient === c.id 
                            ? "bg-primary/20 border-primary text-primary" 
                            : "bg-surface border-white/5 hover:border-white/10"
                      )}
                   >
                      <div className={clsx("w-1.5 h-1.5 rounded-full", c.connected ? "bg-green-500" : "bg-red-500")} />
                      {c.id}
                   </button>
                ))}
                {state.clients.length === 0 && <span className="text-xs text-gray-600 py-1">No active clients</span>}
             </div>
          </div>

          <div className="p-4 flex-1 flex flex-col">
             <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-2">
                <Send size={14} /> Message Console
             </h2>
             <div className="bg-black/20 rounded-lg p-3 border border-white/5 flex-1 flex flex-col">
                <div className="flex-1 flex items-center justify-center text-center p-4">
                   {!selectedClient ? (
                      <span className="text-gray-600 text-sm">Select a client to send messages</span>
                   ) : (
                      <div className="w-full">
                         <div className="mb-4">
                            <span className="text-xs text-gray-500 uppercase">Sending as</span>
                            <div className="text-lg font-bold text-green-400">{selectedClient}</div>
                         </div>
                         <form onSubmit={sendMessage} className="flex gap-2">
                           <input 
                              type="text" 
                              value={message}
                              onChange={e => setMessage(e.target.value)}
                              placeholder="Type command..."
                              className="flex-1 bg-surface border border-white/10 rounded px-3 py-2 text-sm focus:outline-none focus:border-primary/50 transition-colors"
                              autoFocus
                           />
                           <Button type="submit" variant="primary" disabled={!message}>
                              <Send size={14} />
                           </Button>
                        </form>
                      </div>
                   )}
                </div>
             </div>
             
             {/* Simple Active List Bottom */}
             <div className="mt-4 border-t border-white/5 pt-4 overflow-y-auto max-h-[200px]">
                 <h3 className="text-[10px] uppercase font-bold text-gray-600 mb-2">Connected Clients List</h3>
                 {state.clients.map(c => (
                    <div key={c.id} className="flex items-center justify-between text-xs py-1 px-2 hover:bg-white/5 rounded">
                       <span className={clsx(c.connected ? "text-gray-300" : "text-gray-600 line-through")}>{c.id}</span>
                       <button onClick={() => removeClient(c.id)} className="text-gray-600 hover:text-red-400">
                          <Trash2 size={12} />
                       </button>
                    </div>
                 ))}
             </div>
          </div>
        </div>

        {/* COL 3: LOGS */}
        <div className="flex-1 bg-surface/10 p-4 flex flex-col min-w-0">
          <div className="flex items-center justify-between mb-2">
             <h2 className="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                <Monitor size={14} /> System Terminal
             </h2>
             <Button size="sm" variant="neutral" onClick={() => setLogs([])} className="!py-0.5 text-[10px]">Clear</Button>
          </div>
          <Terminal logs={logs} />
        </div>

      </div>
    </div>
  );
}

export default App;
