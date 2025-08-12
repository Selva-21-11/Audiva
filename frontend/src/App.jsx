import React, { useRef, useState } from "react";
import { Room, createLocalTracks, RoomEvent } from "livekit-client";

export default function JoinRoom() {
  const [identity, setIdentity] = useState("user-" + Math.floor(Math.random() * 1000));
  const [roomName, setRoomName] = useState("test-room");
  const [connected, setConnected] = useState(false);
  const roomRef = useRef(null);
  const audioContainerRef = useRef(null);

  async function getToken() {
    const resp = await fetch("http://localhost:8000/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room: roomName, identity }),
    });

    console.log("Token request status:", resp.status);
    const text = await resp.text();
    console.log("Token response text:", text);

    if (!resp.ok) {
      throw new Error(`Error ${resp.status}: ${text || resp.statusText}`);
    }

    return JSON.parse(text);
  }

  async function join() {
    try {
      const { token, url } = await getToken();
      console.log("Received LiveKit URL:", url);
      console.log("Received Access Token:", token);

      const room = new Room();
      roomRef.current = room;

      room
        .on(RoomEvent.TrackSubscribed, (track, pub, participant) => {
          console.log("Track subscribed from:", participant.identity, track.kind);
          if (track.kind === "audio") {
            const el = track.attach();
            el.autoplay = true;
            audioContainerRef.current?.appendChild(el);
          }
        })
        .on(RoomEvent.TrackUnsubscribed, (track, pub, participant) => {
          console.log("Track unsubscribed from:", participant.identity);
          try { track.detach(); } catch { }
        })
        .on(RoomEvent.Disconnected, () => {
          console.log("Disconnected from room");
          setConnected(false);
        })
        .on(RoomEvent.MediaDevicesError, (err) => {
          console.error("Media device error:", err);
          alert("Could not access microphone. Please check permissions.");
        });

      await room.connect(url, token);
      console.log("Successfully connected to room:", room.name);

      const tracks = await createLocalTracks({ audio: true, video: false });
      if (tracks.length) {
        await room.localParticipant.publishTrack(tracks[0]);
        console.log("Microphone track published");
      } else {
        console.warn("No local tracks published; permission might be blocked.");
      }

      setConnected(true);
    } catch (err) {
      console.error("Error during join:", err);
      alert("Failed to join LiveKit room. Check console for details.");
    }
  }

  return (
    <div>
      <div>
        <input value={identity} onChange={(e) => setIdentity(e.target.value)} />
        <input value={roomName} onChange={(e) => setRoomName(e.target.value)} />
        <button onClick={join} disabled={connected}>Join</button>
      </div>
      <div ref={audioContainerRef}></div>
    </div>
  );
}