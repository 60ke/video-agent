import React from "react";
import {AbsoluteFill, interpolate} from "remotion";
import type {V4EffectProps, V4Layout} from "../types";

type Props = {
  effect: V4EffectProps;
  absoluteFrame: number;
  children: React.ReactNode;
};

const eventRevealFrames = (effect: V4EffectProps): number => {
  const fromParams = effect.parameters?.reveal_frames;
  if (typeof fromParams === "number" && fromParams >= 1) {
    return fromParams;
  }
  const event = effect.events[0];
  if (event) {
    return Math.max(1, event.end_frame - event.start_frame);
  }
  if (effect.variant_id === "full") return 12;
  if (effect.variant_id === "compact") return 8;
  return 1;
};

const LightSweepLayer: React.FC<{
  effect: V4EffectProps;
  absoluteFrame: number;
  children: React.ReactNode;
}> = ({effect, absoluteFrame, children}) => {
  const hit = effect.events[0]?.hit_frame ?? effect.start_frame;
  const local = Math.max(0, absoluteFrame - hit);
  const frames = Math.max(eventRevealFrames(effect), effect.end_frame - effect.start_frame);
  const t = interpolate(local, [0, frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const sweepX = -40 + t * 140;
  // Keep the underlying asset visible; light_sweep is an overlay, not a replacement.
  return (
    <AbsoluteFill style={{overflow: "hidden"}}>
      <AbsoluteFill>{children}</AbsoluteFill>
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background: `radial-gradient(ellipse at 50% 42%, rgba(255, 244, 220, ${0.08 + 0.14 * t}) 0%, transparent 58%)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 0,
          bottom: 0,
          left: `${sweepX}%`,
          width: "42%",
          pointerEvents: "none",
          background:
            "linear-gradient(90deg, transparent 0%, rgba(255,236,200,0.18) 35%, rgba(255,255,255,0.55) 50%, rgba(255,236,200,0.18) 65%, transparent 100%)",
          filter: "blur(1px)",
        }}
      />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: 0.2 + 0.25 * Math.sin(t * Math.PI),
          boxShadow: "inset 0 0 120px rgba(255, 230, 180, 0.18)",
        }}
      />
    </AbsoluteFill>
  );
};

export const EffectStage: React.FC<Props> = ({effect, absoluteFrame, children}) => {
  if (effect.effect_id === "light_sweep") {
    return (
      <LightSweepLayer effect={effect} absoluteFrame={absoluteFrame}>
        {children}
      </LightSweepLayer>
    );
  }

  const hit = effect.events[0]?.hit_frame ?? effect.start_frame;
  const local = Math.max(0, absoluteFrame - hit);
  const frames = eventRevealFrames(effect);
  const t = interpolate(local, [0, frames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  let transform = "none";
  let opacity = 1;
  switch (effect.effect_id) {
    case "fade_in":
    case "result_reveal":
      opacity = t;
      break;
    case "detail_push_in":
      transform = `scale(${0.92 + 0.08 * t})`;
      break;
    case "spring_card_pop":
      transform = `scale(${0.85 + 0.15 * t})`;
      break;
    case "slide_gallery":
    case "card_stack":
      transform =
        effect.direction === "right"
          ? `translateX(${(1 - t) * 80}px)`
          : `translateX(${(1 - t) * -80}px)`;
      break;
    case "card_flip_3d":
    case "paper_curl_flip":
      transform = `perspective(1200px) rotateY(${(1 - t) * 70}deg)`;
      break;
    case "before_after":
    case "grid_reveal":
      opacity = 0.55 + 0.45 * t;
      break;
    case "brand_breath":
      transform = `scale(${1 + Math.sin(local / 12) * 0.02})`;
      break;
    case "full_bleed_to_safe_card":
      transform = `scale(${1.08 - 0.08 * t})`;
      break;
    case "none":
      break;
    default:
      throw new Error(`Missing Remotion adapter for effect_id=${effect.effect_id}`);
  }

  return (
    <div style={{width: "100%", height: "100%", opacity, transform, transformOrigin: "center"}}>
      {children}
    </div>
  );
};

export const layoutBox = (layout: V4Layout): React.CSSProperties => ({
  position: "absolute",
  left: layout.x,
  top: layout.y,
  width: layout.width,
  height: layout.height,
  borderRadius: layout.border_radius,
  overflow: "hidden",
  opacity: layout.opacity,
});
