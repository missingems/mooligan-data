// Firebase web config from the console (Project settings → Your apps → Web app).
// These values identify the project; they are not secrets. Until projectId is
// filled in, the site runs on the sample data in sample/data.json.
export default {
  firebase: {
    apiKey: "",
    authDomain: "",
    projectId: "",
    appId: "",
  },
  // Must match FUNCTIONS_REGION in functions/.env.
  functionsRegion: "us-central1",
  formats: ["modern", "standard", "pioneer"],
  timeframes: ["30d", "7d"],
};
