/* Optional. Copy this file to config.js (same folder as index.html) to preconfigure Gemini.
   config.js is git-ignored. Never commit or share a file that contains a real key.
   You can instead enter the key in Settings → AI provider, which stores it in this browser only. */
window.NS_CONFIG = {
  GEMINI_API_KEY: '',                 // your Google AI Studio / Gemini API key
  GEMINI_MODEL: 'gemini-2.5-flash',   // any Gemini Flash model your key can use
  GEMINI_CONSENT: false               // set true to confirm case text may be sent to Google
};
