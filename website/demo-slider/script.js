/* ============================================================
   TIMED CARD OPENING HERO SLIDER — script.js
   Vanilla JS + GSAP. Autoplay 6 detik, kartu membesar jadi
   background hero, teks fade-in dari bawah, baris bergeser kiri.
   ============================================================ */

const AUTOPLAY_MS = 6000;

const SLIDES = [
  {
    img: "img/slide-ps-tv.jpg",
    tagline: "— BILLING PS / TV",
    title: "Billing PS3, PS4 & Android TV Sekali Klik",
    desc: "Kelola sesi main PS dan TV dari kasir: paket per menit, kontrol kartu TV di layar, dan tagihan otomatis saat waktu habis.",
    cta: { href: "https://rrbilling-web.web.app", label: "Explore" }
  },
  {
    img: "img/slide-warnet.jpg",
    tagline: "— BILLING WARNET",
    title: "Kontrol Penuh untuk Rental Warnet",
    desc: "Kunci PC otomatis, sesi main bebas, dan pemantauan semua komputer dari satu dashboard kasir yang rapi dan cepat.",
    cta: { href: "https://rrbilling-web.web.app", label: "Explore" }
  },
  {
    img: "img/slide-laporan.png",
    tagline: "— LAPORAN CLOUD",
    title: "Laporan Pendapatan Real-Time di Cloud",
    desc: "Riwayat transaksi tersinkron otomatis. Pantau pendapatan dari HP dengan akun Google, export CSV, semua dalam satu tempat.",
    cta: { href: "https://rrbilling-web.web.app/laporan.html", label: "Lihat Laporan" }
  },
  {
    img: "img/slide-booking.png",
    tagline: "— BOOKING ONLINE",
    title: "Pelanggan Bisa Booking Dari Rumah",
    desc: "Setiap rental punya halaman booking sendiri: rrcctv.online/b/username. Kasir konfirmasi langsung lewat aplikasi.",
    cta: { href: "https://rrbilling-web.web.app/booking.html", label: "Coba Booking" }
  },
  {
    img: "img/slide-app-android.jpg",
    tagline: "— APLIKASI BILLING ANDROID",
    title: "Aplikasi Billing Android untuk Kasir",
    desc: "Mulai sesi atau main bebas, kelola menu F&B, dan kontrol tiap meja dari ponsel — sinkron real-time dengan kasir PC.",
    cta: { href: "https://rrbilling-web.web.app", label: "Lihat Demo" }
  },
  {
    img: "img/slide-waktu-habis.png",
    tagline: "— LOCKSCREEN WAKTU HABIS",
    title: "TV Terkunci Otomatis Saat Waktu Habis",
    desc: "Saat sisa waktu habis, layar TV terkunci dengan rincian tagihan. Pelanggan panggil kasir untuk lanjut main.",
    cta: { href: "https://rrbilling-web.web.app", label: "Lihat Demo" }
  },
  {
    img: "img/slide-overlay.png",
    tagline: "— OVERLAY TIMER & TAGIHAN",
    title: "Timer & Status Pembayaran Selalu Terlihat",
    desc: "Overlay floating di pojok layar: sisa waktu, nama rental, dan status pesanan LUNAS / TAGIHAN — tanpa mengganggu permainan.",
    cta: { href: "https://rrbilling-web.web.app", label: "Lihat Demo" }
  },
  {
    video: "img/promo.mp4",
    tagline: "— TV PROMO VIDEO",
    title: "Video Promo Jalan Otomatis di Layar TV",
    desc: "Kirim video promosi dari kasir. Setiap TV bangun dari tidur, promo diputar sekali lalu kembali ke input terakhir.",
    cta: { href: "https://rrbilling-web.web.app", label: "Lihat Demo" }
  }
];

const slidesEl = document.getElementById("slides");
const trackEl = document.getElementById("cardsTrack");
const titleEl = document.getElementById("slideTitle");
const descEl = document.getElementById("slideDesc");
const tagEl = document.getElementById("slideTag");
const ctaEl = document.getElementById("ctaBtn");
const counterEl = document.getElementById("counter");

let current = 0;
let timer = null;
let animating = false;
let activeProgress = null;

/* ---------- Bangun layer slide + kartu ---------- */
const layers = [];
SLIDES.forEach((s, i) => {
  const layer = document.createElement("div");
  layer.className = "slide" + (i === 0 ? " active" : "");
  if (s.video) {
    const video = document.createElement("video");
    video.src = s.video;
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    video.preload = "metadata";
    layer.appendChild(video);
  } else {
    layer.style.backgroundImage = `url(${s.img})`;
  }
  slidesEl.appendChild(layer);
  layers.push(layer);

  const card = document.createElement("div");
  card.className = "card" + (i === 0 ? " active" : "") + (s.video ? " video" : "");
  card.dataset.index = i;
  if (!s.video) {
    card.style.setProperty("--thumb", `url(${s.img})`);
  }
  card.innerHTML =
    `<span class="progress"></span>` +
    (s.video ? `<span class="play">▶</span>` : "") +
    `<span class="label">${s.title}</span>`;
  card.addEventListener("click", () => goTo(i, card));
  trackEl.appendChild(card);
});

/* ---------- Animasikan baris kartu geser ke kiri ---------- */
function shiftCards(index) {
  const cards = [...trackEl.children];
  if (!cards[index]) return;
  const wrap = trackEl.parentElement;
  const wrapRect = wrap.getBoundingClientRect();
  const cardRect = cards[index].getBoundingClientRect();
  const isMobile = window.innerWidth <= 720;
  const targetLeft = isMobile ? 10 : wrapRect.width / 2 - cardRect.width / 2;
  const offsetX = cardRect.left - wrapRect.left - targetLeft;
  gsap.to(trackEl, { x: -offsetX, duration: 0.9, ease: "power3.out" });
}

/* ---------- Konten fade-in dari bawah ---------- */
function animateContent(i) {
  const s = SLIDES[i];
  titleEl.textContent = s.title;
  descEl.textContent = s.desc;
  tagEl.textContent = s.tagline;
  ctaEl.href = s.cta.href;
  ctaEl.textContent = s.cta.label;
  counterEl.textContent =
    `${String(i + 1).padStart(2, "0")} / ${String(SLIDES.length).padStart(2, "0")}`;

  gsap.fromTo(
    [tagEl, titleEl, descEl, ctaEl],
    { y: 64, opacity: 0 },
    { y: 0, opacity: 1, duration: 0.85, ease: "power3.out", stagger: 0.1, delay: 0.18 }
  );
}

/* ---------- Transisi utama: kartu membesar jadi hero ---------- */
function goTo(index, cardEl) {
  if (animating) return;
  index = (index + SLIDES.length) % SLIDES.length;
  if (index === current && !cardEl) return;
  const card = cardEl || [...trackEl.children][index];
  if (!card) return;

  animating = true;
  resetTimer();

  const rect = card.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const scaleX = rect.width / vw;
  const scaleY = rect.height / vh;

  const next = layers[index];
  const prev = layers[current];

  // video: mulai putar saat kartu membentang
  const videoEl = next.querySelector("video");
  if (videoEl) {
    videoEl.currentTime = 0;
    videoEl.play().catch(() => {});
  }

  // layer baru diposisikan seukuran kartu
  gsap.set(next, {
    zIndex: 2,
    opacity: 1,
    visibility: "visible",
    transformOrigin: "left top",
    x: rect.left,
    y: rect.top,
    scaleX,
    scaleY,
    borderRadius: "14px"
  });

  // buka: membentang penuh layar
  gsap.to(next, {
    x: 0, y: 0, scaleX: 1, scaleY: 1, borderRadius: "0px",
    duration: 1.05, ease: "power3.inOut",
    onComplete() {
      layers.forEach((l, i) => {
        if (i !== index) gsap.set(l, { zIndex: "", visibility: "hidden", opacity: 0 });
      });
      animating = false;
    }
  });

  // layer lama memudar cepat saat tertutup
  if (prev && prev !== next) {
    gsap.to(prev, { opacity: 0.25, duration: 0.9, ease: "power2.out" });
    const pv = prev.querySelector("video");
    if (pv) pv.pause();
  }

  // status kartu + baris
  [...trackEl.children].forEach((c, i) => {
    c.classList.toggle("active", i === index);
    gsap.to(c, { y: i === index ? -6 : 0, scale: i === index ? 1.06 : 1, duration: 0.5, ease: "power2.out" });
  });
  current = index;
  shiftCards(index);
  animateContent(index);
  startProgress(card);
}

/* ---------- Progress bar kartu aktif ---------- */
function startProgress(card) {
  if (activeProgress) activeProgress.kill();
  const bar = card.querySelector(".progress");
  if (!bar) return;
  gsap.set(bar, { scaleX: 0, transformOrigin: "left" });
  activeProgress = gsap.to(bar, { scaleX: 1, duration: AUTOPLAY_MS / 1000, ease: "none" });
}

/* ---------- Autoplay ---------- */
function nextSlide() {
  goTo((current + 1) % SLIDES.length);
}

function resetTimer() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(nextSlide, AUTOPLAY_MS);
}

function stopTimer() {
  if (timer) clearTimeout(timer);
  if (activeProgress) activeProgress.pause();
}

function resumeTimer() {
  resetTimer();
  if (activeProgress) activeProgress.resume();
}

/* ---------- Init ---------- */
window.addEventListener("load", () => {
  animateContent(0);
  shiftCards(0);
  startProgress(trackEl.children[0]);
  resetTimer();
});

window.addEventListener("resize", () => shiftCards(current));

const cardsWrap = document.querySelector(".cards-wrap");
cardsWrap.addEventListener("mouseenter", stopTimer);
cardsWrap.addEventListener("mouseleave", resumeTimer);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopTimer();
  else resumeTimer();
});