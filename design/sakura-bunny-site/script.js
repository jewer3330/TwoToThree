const envelope = document.querySelector('.envelope');
const message = document.querySelector('.message-card strong');
const petalField = document.querySelector('.petal-field');
const soundToggle = document.querySelector('.sound-toggle');

const notes = [
  '你不必一直赶路，<br>花会在你停下时盛开。',
  '今天也请相信，<br>好事正在慢慢靠近。',
  '允许自己松一口气，<br>柔软不是一件坏事。',
  '不着急成为答案，<br>先好好成为你自己。',
  '把心事晒进阳光里，<br>晚风会替你轻轻收好。'
];

let noteIndex = 0;

envelope.addEventListener('click', () => {
  const isOpen = envelope.getAttribute('aria-expanded') === 'true';

  if (isOpen) {
    envelope.setAttribute('aria-expanded', 'false');
    window.setTimeout(() => {
      noteIndex = (noteIndex + 1) % notes.length;
      message.innerHTML = notes[noteIndex];
      envelope.setAttribute('aria-expanded', 'true');
      createBurst(envelope.getBoundingClientRect());
    }, 600);
  } else {
    envelope.setAttribute('aria-expanded', 'true');
    createBurst(envelope.getBoundingClientRect());
  }
});

document.querySelectorAll('.spring-list button').forEach((item) => {
  item.addEventListener('click', () => {
    const checked = item.getAttribute('aria-pressed') === 'true';
    item.setAttribute('aria-pressed', String(!checked));
    if (!checked) createBurst(item.getBoundingClientRect(), 7);
  });
});

soundToggle.addEventListener('click', () => {
  const active = soundToggle.getAttribute('aria-pressed') === 'true';
  soundToggle.setAttribute('aria-pressed', String(!active));
  soundToggle.querySelector('span:last-child').textContent = active ? '听见春天' : '春风轻响';
  if (!active) sprinklePetals(10);
});

function createBurst(rect, count = 12) {
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;

  for (let i = 0; i < count; i += 1) {
    const petal = document.createElement('i');
    petal.className = 'petal burst';
    petal.style.setProperty('--x', `${centerX + (Math.random() - .5) * 100}px`);
    petal.style.setProperty('--y', `${centerY + (Math.random() - .5) * 50}px`);
    petal.style.setProperty('--dx', `${(Math.random() - .5) * 180}px`);
    petal.style.setProperty('--dy', `${-40 - Math.random() * 100}px`);
    petal.style.transform = `rotate(${Math.random() * 180}deg)`;
    petalField.appendChild(petal);
    window.setTimeout(() => petal.remove(), 1100);
  }
}

function sprinklePetals(count = 1) {
  for (let i = 0; i < count; i += 1) {
    window.setTimeout(() => {
      const petal = document.createElement('i');
      petal.className = 'petal';
      petal.style.left = `${Math.random() * 100}vw`;
      petal.style.setProperty('--drift', `${(Math.random() - .5) * 220}px`);
      petal.style.animationDuration = `${7 + Math.random() * 5}s`;
      petal.style.opacity = String(.35 + Math.random() * .5);
      petalField.appendChild(petal);
      window.setTimeout(() => petal.remove(), 12500);
    }, i * 220);
  }
}

if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  sprinklePetals(7);
  window.setInterval(() => sprinklePetals(1), 2600);
}
