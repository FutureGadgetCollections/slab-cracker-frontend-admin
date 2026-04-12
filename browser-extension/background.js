// Opens a PSA cert page in a new tab when the admin site asks.
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "requestCert" && msg.cert_number) {
    chrome.tabs.create({
      url: `https://www.psacard.com/cert/${msg.cert_number}`,
    });
    sendResponse({ ok: true });
  }
  return true;
});
