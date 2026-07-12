window.loadVerificationSettings = function() {
  api('/admin/verification-settings').then(function(s) {
    document.getElementById('verificationAccountMode').value = s.verification_account_mode || 'either';
    document.getElementById('verificationChannel').value = s.verification_channel || 'debug';
    document.getElementById('smtpHost').value = s.smtp_host || '';
    document.getElementById('smtpPort').value = s.smtp_port || '465';
    document.getElementById('smtpUsername').value = s.smtp_username || '';
    document.getElementById('smtpPassword').value = s.smtp_password || '';
    document.getElementById('smtpFrom').value = s.smtp_from || '';
    document.getElementById('smtpUseSsl').value = s.smtp_use_ssl || '1';
    document.getElementById('emailSubject').value = s.email_subject || '云窑验证码';
    document.getElementById('emailBodyTemplate').value = s.email_body_template || '您的验证码是 {{code}}，10分钟内有效。';
    document.getElementById('smsApiUrl').value = s.sms_api_url || '';
    document.getElementById('smsMethod').value = s.sms_method || 'POST';
    document.getElementById('smsHeadersJson').value = s.sms_headers_json || '{}';
    document.getElementById('smsBodyTemplate').value = s.sms_body_template || '{"phone":"{{phone}}","code":"{{code}}"}';
  }).catch(function(e) {
    toast('加载失败: ' + (e.message || e), 'error');
  });
};

window.saveVerificationSettings = function() {
  var data = {
    verification_account_mode: document.getElementById('verificationAccountMode').value,
    verification_channel: document.getElementById('verificationChannel').value,
    smtp_host: document.getElementById('smtpHost').value,
    smtp_port: document.getElementById('smtpPort').value,
    smtp_username: document.getElementById('smtpUsername').value,
    smtp_password: document.getElementById('smtpPassword').value,
    smtp_from: document.getElementById('smtpFrom').value,
    smtp_use_ssl: document.getElementById('smtpUseSsl').value,
    email_subject: document.getElementById('emailSubject').value,
    email_body_template: document.getElementById('emailBodyTemplate').value,
    sms_api_url: document.getElementById('smsApiUrl').value,
    sms_method: document.getElementById('smsMethod').value,
    sms_headers_json: document.getElementById('smsHeadersJson').value,
    sms_body_template: document.getElementById('smsBodyTemplate').value
  };
  try { JSON.parse(data.sms_headers_json || '{}'); } catch(e) {
    toast('Headers JSON 格式不正确', 'error'); return;
  }
  api('/admin/verification-settings', {
    method: 'PUT',
    body: JSON.stringify(data)
  }).then(function() {
    toast('验证码配置已保存');
    window.loadVerificationSettings();
  }).catch(function(e) {
    toast(e.message || '保存失败', 'error');
  });
};

window.loadVerificationSettings();
