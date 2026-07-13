import { initializeApp } from "firebase/app";
import { getAuth, signInWithPhoneNumber, RecaptchaVerifier } from "firebase/auth";
import { firebaseConfig } from "./firebaseConfig";

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

export function resetRecaptcha() {
  if (window.recaptchaVerifier) {
    if (typeof window.recaptchaVerifier.clear === "function") {
      try {
        window.recaptchaVerifier.clear();
      } catch (err) {
        console.warn("Failed to clear existing RecaptchaVerifier:", err);
      }
    }
    window.recaptchaVerifier = null;
  }
}

export async function setupRecaptcha(containerId = "recaptcha-container") {
  const container = document.getElementById(containerId);
  if (!container) {
    throw new Error(`Recaptcha container not found: ${containerId}`);
  }

  resetRecaptcha();

  // Firebase v9/v10 modular SDK constructor order:
  // new RecaptchaVerifier(auth, containerOrId, parameters)
  window.recaptchaVerifier = new RecaptchaVerifier(
    auth,
    containerId,
    {
      size: "invisible",
      callback: () => {},
    }
  );

  await window.recaptchaVerifier.render();
  return window.recaptchaVerifier;
}

export async function requestSmsCode(phoneNumber) {
  const verifier = await setupRecaptcha();
  return signInWithPhoneNumber(auth, phoneNumber, verifier);
}

export async function getIdToken() {
  const user = auth.currentUser;
  if (!user) return null;
  return user.getIdToken();
}
