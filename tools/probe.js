(async () => {
  const query = (method, parameters) => new Promise((resolve, reject) => {
    const request = { command: 'QUERY_IPC_EXTENSION_MESSAGE', system: 'CrimsonNative', module: 'ShareServer', method };
    if (parameters) request.payload = parameters;
    window.cefQuery({ request: JSON.stringify(request), persistent: false,
      onSuccess: value => { try { resolve(JSON.parse(value)); } catch { resolve(value); } },
      onFailure: (code, message) => reject({ code, message, method }),
    });
  });
  const results = {};
  for (const method of ['GetSupportedResolutionsCodecs', 'GetInstantReplaySettings', 'GetInstantReplayEnableStatus', 'GetRecordEnableStatus', 'GetRecordRunningStatus', 'GetRecordSettings', 'GetHevcSupportedState', 'GetMicMode', 'GetAudioMode', 'GetMicCount']) {
    try { results[method] = await query(method); }
    catch (error) { results[method] = error; }
  }
  return results;
})();
