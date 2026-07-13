// VerifyGate.jsx — transparent-until-verified overlay.
// Two steps: phone number -> 6-digit OTP. On success, calls onVerified().
// This gate now validates against backend Firebase OTP records.

import { useEffect, useRef, useState } from "react";
import { requestSmsCode, getIdToken, resetRecaptcha } from "./firebaseAuth";
import "./verify_gate.css";

const CODE_TTL_SECONDS = 60; // how long the local countdown runs

// normalize a typed number toward E.164 (keep leading +, strip spaces/dashes)
const normalize = (s) => (s || "").replace(/[^\d+]/g, "");

export default function VerifyGate({ onVerified }) {
  const [step, setStep] = useState("phone");     // "phone" | "otp"
  const [phone, setPhone] = useState("");
  const [digits, setDigits] = useState(["", "", "", "", "", ""]);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [expired, setExpired] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const inputsRef = useRef([]);
  const timerRef = useRef(null);

  // countdown for code expiry
  useEffect(() => {
    if (secondsLeft <= 0) return;
    timerRef.current = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) { clearInterval(timerRef.current); setExpired(true); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, [secondsLeft]);

  async function sendCode() {
    if (sending) return;

    setError("");
    const p = normalize(phone);
    if (!p) {
      setError("Enter a valid phone number.");
      return;
    }

    try {
      setSending(true);
      const confirmationResult = await requestSmsCode(p);
      window.confirmationResult = confirmationResult;
      setStep("otp");
      setDigits(["", "", "", "", "", ""]);
      setExpired(false);
      setSecondsLeft(CODE_TTL_SECONDS);
      setTimeout(() => inputsRef.current[0]?.focus(), 50);
    } catch (err) {
      resetRecaptcha();
      setError(err.message || "Unable to request SMS code.");
    } finally {
      setSending(false);
    }
  }

  async function verifyCode() {
    setError("");
    if (expired) {
      setError("Code expired. Please resend.");
      return;
    }

    const code = digits.join("");
    if (code.length < 6) {
      setError("Enter all 6 digits.");
      return;
    }

    try {
      if (!window.confirmationResult) {
        throw new Error("No SMS confirmation flow exists. Send code again.");
      }

      const result = await window.confirmationResult.confirm(code);
      const idToken = await getIdToken();
      if (!idToken) {
        throw new Error("Unable to get Firebase ID token after sign-in.");
      }

      const res = await fetch("/api/auth/verify-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id_token: idToken }),
      });

      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload.detail || "Verification failed.");
      }

      clearInterval(timerRef.current);
      onVerified();
    } catch (err) {
      setError(err.message || "Unable to verify code.");
    }
  }

  async function resend() {
    setError("");
    setExpired(false);
    setSecondsLeft(CODE_TTL_SECONDS);
    setDigits(["", "", "", "", "", ""]);
    setTimeout(() => inputsRef.current[0]?.focus(), 50);
    await sendCode();
  }

  // OTP box handlers: type to advance, backspace to go back, paste to fill all.
  function onDigit(i, v) {
    const c = v.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[i] = c;
    setDigits(next);
    if (c && i < 5) inputsRef.current[i + 1]?.focus();
  }
  function onKey(i, e) {
    if (e.key === "Backspace" && !digits[i] && i > 0) inputsRef.current[i - 1]?.focus();
    if (e.key === "Enter") verifyCode();
  }
  function onPaste(e) {
    const txt = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6);
    if (!txt) return;
    e.preventDefault();
    const next = txt.split("").concat(Array(6).fill("")).slice(0, 6);
    setDigits(next);
    inputsRef.current[Math.min(txt.length, 5)]?.focus();
  }

  return (
    <div className="lock-overlay">
      <div className="verify-card">
        <div className="lock" />
        <h2>Verification Required</h2>

        {step === "phone" ? (
          <>
            <p>Enter your registered phone number to receive a verification code.</p>
            <input
              className="verify-phone"
              placeholder="+1 555 555 0123"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendCode()}
            />
            <div id="recaptcha-container" style={{ visibility: "hidden", height: 0 }} />
            {error && <div className="verify-expired">{error}</div>}
            <button className="verify-btn" onClick={sendCode} disabled={sending}>{sending ? "Sending..." : "Send Code"}</button>
          </>
        ) : (
          <>
            <p>Enter the 6-digit code sent to {normalize(phone)}.</p>
            <div className="otp" onPaste={onPaste}>
              {digits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => (inputsRef.current[i] = el)}
                  value={d}
                  inputMode="numeric"
                  maxLength={1}
                  onChange={(e) => onDigit(i, e.target.value)}
                  onKeyDown={(e) => onKey(i, e)}
                />
              ))}
            </div>
            {expired
              ? <div className="verify-expired">Code expired.</div>
              : secondsLeft > 0 && <p style={{ fontSize: 13, opacity: .6 }}>Expires in {secondsLeft}s</p>}
            {error && <div className="verify-expired">{error}</div>}
            <button className="verify-btn" onClick={verifyCode} disabled={expired}>Verify</button>
            <button className="verify-link" onClick={resend}>Resend code</button>
          </>
        )}
      </div>
    </div>
  );
}
