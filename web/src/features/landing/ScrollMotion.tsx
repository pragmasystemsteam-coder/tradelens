"use client";

import { useEffect } from "react";

// Scroll motion for the landing page: sections and cards ease up as they enter the screen
// (cards in a row are staggered), and the header gains a shadow once the page scrolls.
// Content is fully visible without JavaScript or with reduced motion: only elements still
// below the fold when this runs are hidden, and only until they are reached.
const TARGETS = [
  ".lp-section > h2",
  ".lp-who > div",
  ".lp-feature",
  ".lp-steps > li",
  ".lp-price-head",
  ".lp-plan",
  ".lp-legal",
].join(", ");

export function ScrollMotion() {
  useEffect(() => {
    const header = document.querySelector<HTMLElement>(".public-header");
    const onScroll = () => {
      if (header) header.toggleAttribute("data-scrolled", window.scrollY > 8);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      return () => window.removeEventListener("scroll", onScroll);
    }
    const fold = window.innerHeight;
    const pending = Array.from(document.querySelectorAll<HTMLElement>(TARGETS)).filter(
      (el) => el.getBoundingClientRect().top > fold * 0.92,
    );
    for (const el of pending) {
      const siblings = el.parentElement
        ? Array.from(el.parentElement.children).filter((c) => c.matches(TARGETS))
        : [el];
      el.style.setProperty("--reveal-delay", `${Math.max(0, siblings.indexOf(el)) * 80}ms`);
      el.classList.add("reveal", "reveal--pending");
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          e.target.classList.remove("reveal--pending");
          observer.unobserve(e.target);
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
    );
    pending.forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
      pending.forEach((el) => el.classList.remove("reveal", "reveal--pending"));
    };
  }, []);
  return null;
}
