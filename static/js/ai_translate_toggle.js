// AI 친화 통역 토글 (백로그 066 사이클 3, UI 옵션 A).
// 원본 default. 사용자가 ✨ AI 친화 보기 클릭 → ai_friendly_title/summary 전환.
// localStorage 'translate_mode' 로 선택 유지.

(function () {
  'use strict';
  var KEY = 'translate_mode';

  function applyMode(mode) {
    var isAI = (mode === 'ai');
    document.body.classList.toggle('translate-mode-ai', isAI);

    var btnOrig = document.querySelectorAll('.btn-original');
    var btnAI = document.querySelectorAll('.btn-ai');
    btnOrig.forEach(function (b) {
      b.classList.toggle('active', !isAI);
      b.setAttribute('aria-pressed', String(!isAI));
    });
    btnAI.forEach(function (b) {
      b.classList.toggle('active', isAI);
      b.setAttribute('aria-pressed', String(isAI));
    });
  }

  window.setTranslateMode = function (mode) {
    if (mode !== 'original' && mode !== 'ai') return;
    try { localStorage.setItem(KEY, mode); } catch (e) { /* SSR / private mode */ }
    applyMode(mode);
  };

  document.addEventListener('DOMContentLoaded', function () {
    var saved = 'original';
    try { saved = localStorage.getItem(KEY) || 'original'; } catch (e) {}
    applyMode(saved);
  });
})();
