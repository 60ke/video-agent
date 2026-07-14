import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { RenderShot, SubtitleCue, TimelineProps } from "./types";

const clamp = (value: number) => Math.max(0, Math.min(1, value));
const easeOut = (value: number) => 1 - Math.pow(1 - clamp(value), 3);
const easeInOut = (value: number) => {
  const progress = clamp(value);
  return progress < 0.5 ? 4 * progress ** 3 : 1 - Math.pow(-2 * progress + 2, 3) / 2;
};

const Grid = () => (
  <AbsoluteFill
    style={{
      backgroundColor: "#070a0e",
      backgroundImage:
        "linear-gradient(rgba(53,62,74,.45) 1px, transparent 1px), linear-gradient(90deg, rgba(53,62,74,.45) 1px, transparent 1px), linear-gradient(rgba(25,31,38,.72) 1px, transparent 1px), linear-gradient(90deg, rgba(25,31,38,.72) 1px, transparent 1px)",
      backgroundSize: "128px 128px, 128px 128px, 32px 32px, 32px 32px",
    }}
  />
);

const assetUrl = (assetId: string, assets: TimelineProps["assets"]) => {
  const asset = assets.find((item) => item.asset_id === assetId);
  if (!asset) throw new Error(`Unknown render asset: ${assetId}`);
  return staticFile(asset.path);
};

const assetFor = (assetId: string, assets: TimelineProps["assets"]) => {
  const asset = assets.find((item) => item.asset_id === assetId);
  if (!asset) throw new Error(`Unknown render asset: ${assetId}`);
  return asset;
};

const sequenceAsset = (shot: RenderShot, frame: number) => {
  const sequence = shot.parameter_sequence;
  if (!sequence) return { assetId: shot.asset_bindings.primary ?? Object.values(shot.asset_bindings)[0], opacity: 1 };
  const fade = Math.max(1, sequence.crossfade_frames);
  if (frame < sequence.start_frame) return { assetId: sequence.base_asset_id, opacity: 1 };
  if (frame < sequence.stage_frame) return { assetId: sequence.stage_asset_id, opacity: easeOut((frame - sequence.start_frame) / fade) };
  if (frame < sequence.hit_frame) return { assetId: sequence.final_asset_id, opacity: easeOut((frame - sequence.stage_frame) / fade) };
  return { assetId: sequence.final_asset_id, opacity: 1 };
};

const MotionImage: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const local = Math.max(0, frame - shot.start_frame);
  const duration = Math.max(1, shot.end_frame - shot.start_frame);
  const progress = clamp(local / duration);
  const selected = sequenceAsset(shot, frame);
  if (shot.motion === "full_bleed_to_safe_card") {
    return <FullBleedToSafeCard assetId={selected.assetId} shot={shot} props={props} />;
  }
  if (shot.motion === "page_turn_3d") {
    return <PageTurnCard assetId={selected.assetId} shot={shot} props={props} />;
  }
  const previous = shot.parameter_sequence && frame >= shot.parameter_sequence.start_frame && frame < shot.parameter_sequence.stage_frame
    ? shot.parameter_sequence.base_asset_id
    : shot.parameter_sequence && frame >= shot.parameter_sequence.stage_frame && frame < shot.parameter_sequence.hit_frame
      ? shot.parameter_sequence.stage_asset_id
      : null;
  const entrance = spring({ frame: local, fps, config: { damping: 200, stiffness: 110, mass: 0.8 } });
  const isDense = shot.template === "ui_params_focus";
  const isEntry = shot.template === "ui_feature_entry";
  const isResult = shot.template === "result_showcase";
  const isPanScan = shot.motion === "image_pan_scan";
  const sourceAsset = props.assets.find((asset) => asset.asset_id === selected.assetId);
  const stageWidth = 856;
  const stageHeight = isDense ? 1260 : 1250;
  const stageRatio = stageWidth / stageHeight;
  const sourceRatio = sourceAsset ? sourceAsset.width / sourceAsset.height : stageRatio;
  // Fit-contain is the opening state. This is the minimum scale that turns a
  // full horizontal image into an edge-to-edge detail view inside the portrait stage.
  const coverScale = sourceRatio > stageRatio ? sourceRatio / stageRatio : stageRatio / sourceRatio;
  const scanTargetScale = Math.min(2.85, Math.max(1.45, coverScale * 1.08));
  const scanBaseWidth = sourceRatio > stageRatio ? stageWidth : stageHeight * sourceRatio;
  const scanBaseHeight = sourceRatio > stageRatio ? stageWidth / sourceRatio : stageHeight;
  const pan = easeOut(progress);
  let scale = 1;
  let x = 0;
  let y = 0;
  let rotateY = 0;
  let opacity = 1;
  if (shot.motion === "fade_in" || shot.motion === "result_reveal") opacity = clamp(local / 8);
  if (shot.motion === "scale_in") scale = isDense ? 0.97 + entrance * 0.035 : 0.86 + entrance * 0.16;
  if (shot.motion === "scale_out") scale = 1.06 - entrance * 0.06;
  if (shot.motion === "detail_push_in") {
    scale = 1.14 + 0.28 * easeOut(Math.min(1, progress / 0.72));
    x = isEntry ? -8 + 5 * pan : 0;
    y = isEntry ? -5 + 3 * pan : 0;
  }
  if (shot.motion === "brand_breath") {
    scale = 1 + Math.sin(local / 10) * 0.018;
    y = Math.sin(local / 14) * -1.4;
  }
  // A virtual camera starts by showing the entire source, then studies it.
  // The movement stays inside the clipped card, so it cannot reveal blank canvas.
  // Hold the whole image briefly, then emulate a deliberate hand-held
  // inspection: zoom -> look left/up -> sweep right -> settle left/down.
  const zoomIn = easeOut(clamp((progress - 0.12) / 0.36));
  const scanProgress = clamp((progress - 0.48) / 0.52);
  // These are image offsets, so the camera travels in the opposite direction.
  const scanXLimit = Math.max(0, (scanBaseWidth * scanTargetScale - stageWidth) / 2);
  const scanYLimit = Math.max(0, (scanBaseHeight * scanTargetScale - stageHeight) / 2);
  const scanX = interpolate(scanProgress, [0, 0.22, 0.62, 1], [0, scanXLimit * 0.88, -scanXLimit * 0.96, scanXLimit * 0.72]);
  const scanY = interpolate(scanProgress, [0, 0.22, 0.62, 1], [0, scanYLimit * 0.86, scanYLimit * 0.46, -scanYLimit * 0.9]);
  const imageTransform = isPanScan
    ? `translate(${scanX}px, ${scanY}px) scale(${1 + (scanTargetScale - 1) * zoomIn})`
    : undefined;
  const cardStyle: React.CSSProperties = {
    position: "absolute",
    left: 100,
    top: isDense ? 270 : 290,
    width: stageWidth,
    height: stageHeight,
    borderRadius: 26,
    overflow: "hidden",
    boxShadow: "10px 22px 34px rgba(0,0,0,.54)",
    opacity,
    transform: `perspective(1800px) translate(${x}%, ${y}%) scale(${scale}) rotateY(${rotateY}deg)`,
    transformOrigin: "center center",
    backgroundColor: isPanScan ? "transparent" : "#10151c",
  };
  const imageStyle: React.CSSProperties = isPanScan
    ? {
        position: "absolute",
        left: (stageWidth - scanBaseWidth) / 2,
        top: (stageHeight - scanBaseHeight) / 2,
        width: scanBaseWidth,
        height: scanBaseHeight,
        objectFit: "fill",
        transform: imageTransform,
        transformOrigin: "center center",
      }
    : {
        width: "100%",
        height: "100%",
        objectFit: isDense ? "contain" : isEntry || isResult ? "cover" : "contain",
        backgroundColor: "#10151c",
      };
  return (
    <AbsoluteFill style={{ perspective: 1800 }}>
      <div style={cardStyle}>
        <Img src={assetUrl(selected.assetId, props.assets)} style={imageStyle} />
        {previous ? <Img src={assetUrl(previous, props.assets)} style={{ ...imageStyle, position: "absolute", inset: 0, opacity: 1 - selected.opacity }} /> : null}
      </div>
    </AbsoluteFill>
  );
};

const PageTurnCard: React.FC<{ assetId: string; shot: RenderShot; props: TimelineProps }> = ({ assetId, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const entrance = easeInOut(local / 22);
  const angle = interpolate(entrance, [0, 0.66, 1], [-76, -12, 0]);
  const scale = interpolate(entrance, [0, 0.7, 1], [0.64, 0.94, 1]);
  const x = interpolate(entrance, [0, 1], [-220, 0]);
  const y = interpolate(entrance, [0, 0.45, 1], [360, -20, 0]);
  const opacity = clamp(local / 4);
  return (
    <AbsoluteFill style={{ perspective: 1600 }}>
      <div
        style={{
          position: "absolute",
          left: 74,
          top: 610,
          width: 932,
          height: 524,
          borderRadius: 28,
          overflow: "hidden",
          opacity,
          transformOrigin: "left center",
          transformStyle: "preserve-3d",
          transform: `translate(${x}px, ${y}px) scale(${scale}) rotateY(${angle}deg)`,
          boxShadow: "0 30px 64px rgba(0,0,0,.58), 0 0 30px rgba(77,156,255,.2)",
          background: "#0a0e14",
        }}
      >
        <Img src={assetUrl(assetId, props.assets)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    </AbsoluteFill>
  );
};

const FullBleedToSafeCard: React.FC<{ assetId: string; shot: RenderShot; props: TimelineProps }> = ({ assetId, shot, props }) => {
  const frame = useCurrentFrame();
  const local = Math.max(0, frame - shot.start_frame);
  const settle = easeInOut(local / 30);
  const asset = assetFor(assetId, props.assets);
  const accent = asset.accent_color ?? "#f5c518";
  const safeWidth = 856;
  const safeHeight = Math.min(1536, safeWidth * asset.height / asset.width);
  const safeTop = (1920 - safeHeight) / 2;
  const left = interpolate(settle, [0, 1], [0, 100]);
  const top = interpolate(settle, [0, 1], [0, safeTop]);
  const width = interpolate(settle, [0, 1], [1080, safeWidth]);
  const height = interpolate(settle, [0, 1], [1920, safeHeight]);
  const radius = interpolate(settle, [0, 1], [0, 28]);
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left,
          top,
          width,
          height,
          overflow: "hidden",
          borderRadius: radius,
          backgroundColor: "#080b0f",
          boxShadow: `0 0 ${interpolate(settle, [0, 1], [0, 34])}px ${accent}, 0 20px 44px rgba(0,0,0,.54)`,
        }}
      >
        <Img src={assetUrl(assetId, props.assets)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        <div style={{ position: "absolute", inset: 0, backgroundColor: accent, opacity: 0.72 * Math.pow(1 - settle, 1.7), mixBlendMode: "color" }} />
        <div style={{ position: "absolute", inset: 0, border: `${interpolate(settle, [0, 1], [0, 5])}px solid ${accent}`, borderRadius: radius, pointerEvents: "none" }} />
      </div>
    </AbsoluteFill>
  );
};

const ReferenceComparison: React.FC<{ shot: RenderShot; props: TimelineProps }> = ({ shot, props }) => {
  const frame = useCurrentFrame();
  const local = frame - shot.start_frame;
  const resultOpacity = clamp((local - 10) / 10);
  const cards = [
    ["实景参考", shot.asset_bindings.reference, 360, 540, 0.92],
    ["生成效果", shot.asset_bindings.result, 970, 540, 1],
  ] as const;
  return <AbsoluteFill>{cards.map(([label, id, top, height, opacity]) => id ? (
    <div key={label} style={{ position: "absolute", left: 132, top, width: 816, height, borderRadius: 24, overflow: "hidden", opacity: label === "生成效果" ? resultOpacity : opacity, boxShadow: "8px 18px 28px rgba(0,0,0,.48)" }}>
      <Img src={assetUrl(id, props.assets)} style={{ width: "100%", height: "100%", objectFit: "contain", background: "#10151c" }} />
      <div style={{ position: "absolute", top: 18, left: 18, padding: "10px 18px", borderRadius: 18, background: "rgba(7,10,14,.82)", color: "#f5f7fb", fontSize: 28, fontWeight: 700 }}>{label}</div>
    </div>
  ) : null)}</AbsoluteFill>;
};

const Subtitle: React.FC<{ cue: SubtitleCue }> = ({ cue }) => {
  const frame = useCurrentFrame();
  const local = frame - cue.start_frame;
  const opacity = clamp(local / 5);
  const top = cue.slot === "subtitle_top" ? 148 : 1340;
  const parts = cue.emphasize && cue.text.includes(cue.emphasize) ? cue.text.split(cue.emphasize) : null;
  return <div style={{ position: "absolute", top, left: 90, width: 760, minHeight: 100, display: "flex", alignItems: "center", justifyContent: "center", color: "#fafafa", fontFamily: "Noto Sans CJK SC, Microsoft YaHei, sans-serif", fontWeight: 800, fontSize: 64, lineHeight: 1.14, whiteSpace: "nowrap", opacity, textShadow: "0 4px 0 #080a0e, 2px 0 0 #080a0e, -2px 0 0 #080a0e" }}>
    {parts ? <>{parts[0]}<span style={{ color: "#ffd44a" }}>{cue.emphasize}</span>{parts[1]}</> : cue.text}
  </div>;
};

export const VerticalDemo: React.FC<TimelineProps> = (props) => {
  const frame = useCurrentFrame();
  const base = props.shots.filter((shot) => shot.track === "base" && shot.start_frame <= frame && frame < shot.end_frame).at(-1);
  const overlays = props.shots.filter((shot) => shot.track === "overlay" && shot.start_frame <= frame && frame < shot.end_frame).sort((a, b) => (a.overlay_layout?.z_index ?? 10) - (b.overlay_layout?.z_index ?? 10));
  const subtitle = props.subtitles.find((cue) => cue.start_frame <= frame && frame < cue.end_frame);
  return <AbsoluteFill><Grid />{base ? base.template === "reference_to_result" ? <ReferenceComparison shot={base} props={props} /> : <MotionImage shot={base} props={props} /> : null}{overlays.map((shot) => <MotionImage key={shot.shot_id} shot={shot} props={props} />)}{subtitle ? <Subtitle cue={subtitle} /> : null}</AbsoluteFill>;
};
