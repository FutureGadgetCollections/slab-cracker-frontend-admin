// Fetches a JSON file: tries GitHub raw first, falls back to GCS.
// Requires window.DATA_CONFIG = { gcsBucket, githubDataRepo }
async function loadJsonData(filename) {
  const { gcsBucket, githubDataRepo } = window.DATA_CONFIG || {};

  console.debug(`[data-loader] loading ${filename} | githubDataRepo=${githubDataRepo} | gcsBucket=${gcsBucket}`);

  // --- Try GitHub raw ---
  if (githubDataRepo) {
    const githubUrl = `https://raw.githubusercontent.com/${githubDataRepo}/main/${filename}?t=${Date.now()}`;
    console.debug(`[data-loader] trying GitHub: ${githubUrl}`);
    try {
      const res = await fetch(githubUrl);
      console.debug(`[data-loader] GitHub response: ${res.status} for ${filename}`);
      if (res.ok) return await res.json();
      console.warn(`[data-loader] GitHub returned ${res.status} for ${filename}, falling back to GCS`);
    } catch (e) {
      console.warn(`[data-loader] GitHub fetch threw for ${filename}:`, e);
    }
  } else {
    console.warn(`[data-loader] githubDataRepo not set, skipping GitHub`);
  }

  // --- Fall back to GCS ---
  if (!gcsBucket) throw new Error('DATA_CONFIG.gcsBucket is not set');
  const gcsUrl = `https://storage.googleapis.com/${gcsBucket}/${filename}?t=${Date.now()}`;
  console.debug(`[data-loader] trying GCS: ${gcsUrl}`);
  try {
    const gcsRes = await fetch(gcsUrl);
    console.debug(`[data-loader] GCS response: ${gcsRes.status} for ${filename}`);
    if (!gcsRes.ok) throw new Error(`GCS fetch failed for ${filename}: ${gcsRes.status}`);
    return await gcsRes.json();
  } catch (e) {
    console.error(`[data-loader] GCS fetch threw for ${filename}:`, e);
    throw e;
  }
}
