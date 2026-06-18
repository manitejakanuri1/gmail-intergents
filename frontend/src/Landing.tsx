import { useEffect, useRef } from "react";
import "./landing.css";

const FEATURES = [
  { i: "🎯", h: "Priority control dashboard", p: "Every email is triaged by urgency and stacked top-down, each showing the exact action to take — with one-tap reminders." },
  { i: "✨", h: "AI summaries", p: "Per-email and full-thread summaries that understand the whole conversation, not one message in isolation." },
  { i: "🗂️", h: "Smart categories", p: "Work, Finance, Job, Personal, Notifications, Newsletters — sorted automatically the moment mail arrives." },
  { i: "💬", h: "Chat with your inbox", p: "Ask in plain English. A RAG agent answers from your real emails and shows the exact source — never makes things up." },
  { i: "✍️", h: "AI compose & reply", p: "Draft a polished email from one line. Replies carry full thread context and slot back into Gmail perfectly." },
  { i: "🔎", h: "Semantic search", p: "Find by meaning, not keywords. “Who rejected me?” surfaces the email that says “we won’t move forward.”" },
];

export default function Landing({ onConnect, busy }: { onConnect: () => void; busy?: boolean }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const root = rootRef.current!;
    root.classList.add("js-on");

    // scroll reveal
    const checkReveal = () => {
      const vh = window.innerHeight || 720;
      root.querySelectorAll(".lp-reveal:not(.in)").forEach((el) => {
        if ((el as HTMLElement).getBoundingClientRect().top < vh * 0.92) el.classList.add("in");
      });
    };
    window.addEventListener("scroll", checkReveal, { passive: true });
    window.addEventListener("resize", checkReveal);
    checkReveal();
    const t = setTimeout(checkReveal, 400);

    // 3D background via Three.js (loaded from CDN once)
    let raf = 0;
    let cleanupThree = () => {};
    const startThree = () => {
      const THREE = (window as any).THREE;
      const canvas = canvasRef.current;
      if (!THREE || !canvas) return;
      const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      const scene = new THREE.Scene();
      const cam = new THREE.PerspectiveCamera(70, 1, 1, 2200);
      cam.position.z = 620;
      const N = 150, R = 820;
      const positions = new Float32Array(N * 3);
      const vel: number[][] = [];
      for (let i = 0; i < N; i++) {
        positions[i * 3] = (Math.random() - 0.5) * R * 2;
        positions[i * 3 + 1] = (Math.random() - 0.5) * R * 1.3;
        positions[i * 3 + 2] = (Math.random() - 0.5) * R;
        vel.push([(Math.random() - 0.5) * 0.4, (Math.random() - 0.5) * 0.4, (Math.random() - 0.5) * 0.4]);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: 3.4, color: 0x9b8cff, transparent: true, opacity: 0.9 }));
      scene.add(pts);
      const lineGeo = new THREE.BufferGeometry();
      const lines = new THREE.LineSegments(lineGeo, new THREE.LineBasicMaterial({ color: 0x4be0ff, transparent: true, opacity: 0.18 }));
      scene.add(lines);
      let mx = 0, my = 0;
      const onMove = (e: MouseEvent) => { mx = e.clientX / window.innerWidth - 0.5; my = e.clientY / window.innerHeight - 0.5; };
      window.addEventListener("mousemove", onMove);
      const resize = () => {
        const w = window.innerWidth || 1280, h = window.innerHeight || 720;
        renderer.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix();
      };
      window.addEventListener("resize", resize); resize();
      const frame = () => {
        if (renderer.domElement.width === 0) resize();
        const p = geo.attributes.position.array as Float32Array;
        for (let i = 0; i < N; i++) {
          p[i * 3] += vel[i][0]; p[i * 3 + 1] += vel[i][1]; p[i * 3 + 2] += vel[i][2];
          const lim = [R, R * 0.65, R * 0.5];
          for (let a = 0; a < 3; a++) if (Math.abs(p[i * 3 + a]) > lim[a]) vel[i][a] *= -1;
        }
        geo.attributes.position.needsUpdate = true;
        const seg: number[] = []; const max2 = 120 * 120;
        for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
          const dx = p[i * 3] - p[j * 3], dy = p[i * 3 + 1] - p[j * 3 + 1], dz = p[i * 3 + 2] - p[j * 3 + 2];
          if (dx * dx + dy * dy + dz * dz < max2) seg.push(p[i * 3], p[i * 3 + 1], p[i * 3 + 2], p[j * 3], p[j * 3 + 1], p[j * 3 + 2]);
        }
        lineGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(seg), 3));
        pts.rotation.y += 0.0008; lines.rotation.y = pts.rotation.y;
        cam.position.x += (mx * 180 - cam.position.x) * 0.04;
        cam.position.y += (-my * 120 - cam.position.y) * 0.04;
        cam.lookAt(0, 0, 0);
        renderer.render(scene, cam);
        raf = requestAnimationFrame(frame);
      };
      frame();
      cleanupThree = () => {
        cancelAnimationFrame(raf);
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("resize", resize);
        renderer.dispose();
      };
    };

    let script: HTMLScriptElement | null = null;
    if ((window as any).THREE) startThree();
    else {
      script = document.createElement("script");
      script.src = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
      script.onload = startThree;
      document.body.appendChild(script);
    }

    return () => {
      window.removeEventListener("scroll", checkReveal);
      window.removeEventListener("resize", checkReveal);
      clearTimeout(t);
      cleanupThree();
    };
  }, []);

  return (
    <div className="landing-page" ref={rootRef}>
      <canvas id="lp-bg3d" ref={canvasRef}></canvas>
      <div className="lp-aurora"></div>
      <div className="lp-content">
        <nav className="lp-nav">
          <div className="lp-logo"><span className="dot">◆</span> Inbox<span className="lp-grad">Intelligence</span></div>
          <div className="lp-links">
            <a href="#lp-problem">Why</a><a href="#lp-features">Features</a><a href="#lp-how">How it works</a><a href="#lp-tech">Tech</a>
          </div>
          <button className="lp-btn lp-primary" onClick={onConnect} disabled={busy}>{busy ? "Connecting…" : "Connect Gmail →"}</button>
        </nav>

        <header className="lp-hero">
          <div className="lp-pill"><span className="live"></span> Live · AI-powered Gmail triage</div>
          <h1>Your inbox, finally <span className="lp-grad">under control.</span></h1>
          <p>An AI command center that reads every email, ranks it by urgency, tells you exactly what to do, and answers any question about your mailbox — with the source to prove it.</p>
          <div className="lp-cta">
            <button className="lp-btn lp-primary" onClick={onConnect} disabled={busy}>{busy ? "Connecting…" : "Get started free →"}</button>
            <a className="lp-btn lp-ghost" href="#lp-features">See the features</a>
          </div>
          <div className="lp-hint">Scroll to explore ↓</div>
        </header>

        <section id="lp-problem" className="lp-wrap lp-sec">
          <div className="lp-reveal">
            <div className="lp-eyebrow">The problem</div>
            <h2 className="lp-title">A flat inbox treats a job offer like a coupon.</h2>
            <p className="lp-sub">Email tools show everything in one endless list, newest first. The urgent and the trivial look identical — so what matters gets buried.</p>
          </div>
          <div className="lp-split">
            <div className="lp-panel bad lp-reveal"><h3>The ordinary inbox</h3><ul>
              <li>Everything in one undifferentiated stream</li><li>No idea what actually needs a reply</li>
              <li>Important threads buried under newsletters</li><li>You re-read emails to remember context</li></ul></div>
            <div className="lp-panel good lp-reveal"><h3>Inbox Intelligence</h3><ul>
              <li>Stacked by urgency — critical items rise to the top</li><li>Every email tells you the one action to take</li>
              <li>Auto-sorted, auto-summarized, instantly searchable</li><li>Ask anything and get a cited answer in seconds</li></ul></div>
          </div>
        </section>

        <section id="lp-features" className="lp-wrap lp-sec">
          <div className="lp-reveal"><div className="lp-eyebrow">What it does</div><h2 className="lp-title">Six features. One calm, intelligent inbox.</h2></div>
          <div className="lp-grid">
            {FEATURES.map((f) => (
              <div className="lp-card lp-reveal" key={f.h}><div className="ico">{f.i}</div><h3>{f.h}</h3><p>{f.p}</p></div>
            ))}
          </div>
        </section>

        <section id="lp-how" className="lp-wrap lp-sec">
          <div className="lp-reveal"><div className="lp-eyebrow">How it works</div><h2 className="lp-title">Connect once. The AI does the rest.</h2></div>
          <div className="lp-steps">
            <div className="lp-step lp-reveal"><div className="num">01</div><h3>Connect your Gmail</h3><p>Secure Google sign-in. We sync your mail, threads, and labels — never your password.</p></div>
            <div className="lp-step lp-reveal"><div className="num">02</div><h3>AI reads &amp; ranks</h3><p>Each email is summarized, categorized, prioritized, and embedded for instant semantic recall.</p></div>
            <div className="lp-step lp-reveal"><div className="num">03</div><h3>You take control</h3><p>Open a calm, prioritized dashboard. Act on what matters. Ask anything. Reply in a click.</p></div>
          </div>
          <div className="lp-stats lp-reveal">
            <div className="lp-stat"><div className="v lp-grad">6</div><div className="l">Smart categories</div></div>
            <div className="lp-stat"><div className="v lp-grad">2</div><div className="l">AI models in tandem</div></div>
            <div className="lp-stat"><div className="v lp-grad">1024</div><div className="l">Dims per email vector</div></div>
            <div className="lp-stat"><div className="v lp-grad">0</div><div className="l">Hallucinated answers</div></div>
          </div>
        </section>

        <section id="lp-tech" className="lp-wrap lp-sec">
          <div className="lp-reveal"><div className="lp-eyebrow">Under the hood</div><h2 className="lp-title">Built on a modern, production-grade stack.</h2>
            <p className="lp-sub">A reasoning model and a retrieval model working in tandem, over a vector-native database — the architecture behind the best AI products.</p></div>
          <div className="lp-tech-row lp-reveal">
            <div className="lp-tech">🧠 <b>Google Gemini</b> · reasoning</div><div className="lp-tech">🔗 <b>NVIDIA NIM</b> · embeddings</div>
            <div className="lp-tech">🐘 <b>Supabase</b> · Postgres + pgvector</div><div className="lp-tech">⚡ <b>FastAPI</b> · async backend</div>
            <div className="lp-tech">⚛️ <b>React</b> · interface</div><div className="lp-tech">📬 <b>Gmail API</b> · OAuth 2.0</div>
          </div>
        </section>

        <section className="lp-wrap">
          <div className="lp-final lp-reveal">
            <h2>Stop managing email.<br /><span className="lp-grad">Start commanding it.</span></h2>
            <p>Connect your Gmail and watch the chaos turn into a calm, prioritized command center.</p>
            <button className="lp-btn lp-primary" style={{ fontSize: 16, padding: "15px 30px" }} onClick={onConnect} disabled={busy}>{busy ? "Connecting…" : "Connect Gmail →"}</button>
          </div>
        </section>

        <footer className="lp-footer">Inbox Intelligence — AI-Powered Gmail Intelligence Platform · Gemini · NVIDIA NIM · Supabase · FastAPI</footer>
      </div>
    </div>
  );
}
