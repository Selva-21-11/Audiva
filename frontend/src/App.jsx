// src/App.jsx
import React, { useRef, useState } from "react";
import { Room, createLocalTracks, RoomEvent } from "livekit-client";

const BACKEND = "http://localhost:8000";

function RecruiterForm({ onReady }) {
  const [role, setRole] = useState("Frontend Engineer");
  const [jd, setJd] = useState("Build features end-to-end in React.");
  const [skills, setSkills] = useState("React,JavaScript,Testing");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function startInterview() {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${BACKEND}/start_interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role,
          jd,
          skills: skills.split(",").map(s => s.trim()).filter(Boolean)
        })
      });
      const j = await resp.json();
      if (!resp.ok) throw new Error(JSON.stringify(j));
      onReady(j); // { token, url, room, identity }
    } catch (err) {
      console.error(err);
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{padding:20, width:420}}>
      <h2>Start Interview</h2>
      <label>Role</label><br/>
      <input value={role} onChange={e=>setRole(e.target.value)} style={{width:"100%"}}/>

      <label>Job description</label><br/>
      <textarea value={jd} onChange={e=>setJd(e.target.value)} style={{width:"100%", height:80}}/>

      <label>Skills (comma separated)</label><br/>
      <input value={skills} onChange={e=>setSkills(e.target.value)} style={{width:"100%"}}/>

      <div style={{marginTop:10}}>
        <button onClick={startInterview} disabled={loading}>{loading ? "Starting..." : "Start & Join as candidate"}</button>
        {error && <div style={{color:"red"}}>{error}</div>}
      </div>
    </div>
  );
}

export default function App() {
  const audioRef = useRef(null);
  const roomRef = useRef(null);
  const [connected, setConnected] = useState(false);

  async function joinAndStart({ token, url }) {
    const roomObj = new Room();
    roomRef.current = roomObj;

    roomObj.on(RoomEvent.TrackSubscribed, (track, pub, participant) => {
      if (track.kind === "audio") {
        const el = track.attach();
        el.autoplay = true;
        audioRef.current?.appendChild(el);
      }
    });

    roomObj.on(RoomEvent.Disconnected, () => setConnected(false));

    try {
      await roomObj.connect(url, token);
      const tracks = await createLocalTracks({ audio: true, video: false });
      if (tracks.length) await roomObj.localParticipant.publishTrack(tracks[0]);
      setConnected(true);
    } catch (err) {
      console.error("join error", err);
      alert("Failed to join: " + err);
    }
  }

  return (
    <div style={{display:"flex", gap:40, padding:20}}>
      <RecruiterForm onReady={joinAndStart} />
      <div>
        <h3>Candidate</h3>
        <div ref={audioRef}></div>
        <div>Status: {connected ? "Connected" : "Idle"}</div>
      </div>
    </div>
  );
}
