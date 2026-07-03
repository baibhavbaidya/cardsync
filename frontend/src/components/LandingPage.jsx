import { useState, useEffect } from 'react';
import { SignInButton, SignUpButton } from '@clerk/clerk-react';
import CardSwap, { Card } from './CardSwap';

function IconEye() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  );
}

function IconShield() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <polyline points="9 12 11 14 15 10"/>
    </svg>
  );
}

function IconMail() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
      <polyline points="22,6 12,13 2,6"/>
    </svg>
  );
}

function IconMic() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      <line x1="12" y1="19" x2="12" y2="23"/>
      <line x1="8" y1="23" x2="16" y2="23"/>
    </svg>
  );
}

function IconCard() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="5" width="20" height="14" rx="2"/>
      <line x1="2" y1="10" x2="22" y2="10"/>
    </svg>
  );
}

export default function LandingPage() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 640);

  useEffect(() => {
    const handler = () => setIsMobile(window.innerWidth <= 640);
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return (
    <div className="landing">
      <nav className="landing-nav">
        <span className="landing-brand">
          <IconCard />
          CardSync
        </span>
        <SignInButton mode="modal">
          <button className="btn-signin-nav">Sign in</button>
        </SignInButton>
      </nav>

      <section className="hero">
        <div className="hero-text">
          <h1 className="hero-headline">
            Digitize visiting cards<br />in seconds
          </h1>
          <p className="hero-sub">
            Upload a card photo, CardSync extracts the contact, logs it to your
            contacts, and notifies your team automatically.
          </p>
          <SignUpButton mode="modal">
            <button className="btn-cta">Get Started Free</button>
          </SignUpButton>
        </div>

        <div className="hero-visual">
          <CardSwap
            width={isMobile ? 260 : 340}
            height={isMobile ? 180 : 200}
            cardDistance={isMobile ? 30 : 60}
            verticalDistance={isMobile ? 30 : 70}
            delay={4000}
            pauseOnHover
            skewAmount={5}
            easing="elastic"
          >
            <Card className="biz-card biz-card--blue">
              <div className="biz-card-inner">
                <div className="biz-card-top">
                  <span className="biz-card-company">TechNova Solutions</span>
                </div>
                <div className="biz-card-bottom">
                  <p className="biz-card-name">Alex Johnson</p>
                  <p className="biz-card-title">Chief Technology Officer</p>
                  <p className="biz-card-contact">alex.johnson@technova.io</p>
                  <p className="biz-card-contact">+1 (415) 555-0182</p>
                </div>
              </div>
            </Card>

            <Card className="biz-card biz-card--teal">
              <div className="biz-card-inner">
                <div className="biz-card-top">
                  <span className="biz-card-company">Meridian Group</span>
                </div>
                <div className="biz-card-bottom">
                  <p className="biz-card-name">Sarah Chen</p>
                  <p className="biz-card-title">VP of Business Development</p>
                  <p className="biz-card-contact">s.chen@meridiangroup.com</p>
                  <p className="biz-card-contact">+1 (628) 555-0247</p>
                </div>
              </div>
            </Card>

            <Card className="biz-card biz-card--dark">
              <div className="biz-card-inner">
                <div className="biz-card-top">
                  <span className="biz-card-company">Nexus Ventures</span>
                </div>
                <div className="biz-card-bottom">
                  <p className="biz-card-name">Michael Torres</p>
                  <p className="biz-card-title">Founder &amp; CEO</p>
                  <p className="biz-card-contact">m.torres@nexusvc.com</p>
                  <p className="biz-card-contact">+1 (212) 555-0391</p>
                </div>
              </div>
            </Card>
          </CardSwap>
        </div>
      </section>

      <section className="features">
        <div className="feature-grid">
          <div className="feature-item">
            <span className="feature-icon"><IconEye /></span>
            <h3>Smart Extraction</h3>
            <p>GPT-4o reads the card and pulls name, phone, email, and company — no manual entry.</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon"><IconShield /></span>
            <h3>Instant Dedup</h3>
            <p>Checks your contacts before every write. The same contact never gets logged twice.</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon"><IconMail /></span>
            <h3>Team Alerts</h3>
            <p>Sends an email notification the moment a new contact is logged.</p>
          </div>
          <div className="feature-item">
            <span className="feature-icon"><IconMic /></span>
            <h3>Voice Notes</h3>
            <p>Record a note after meeting someone. Whisper transcribes and attaches it to the right contact.</p>
          </div>
        </div>
      </section>
    </div>
  );
}
