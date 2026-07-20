import React from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  staticFile,
  useCurrentFrame,
  Video,
} from "remotion";
import {EffectStage, layoutBox} from "./effects";
import {SubtitleTrack} from "./subtitles/SubtitleTrack";
import type {V4EffectProps, V4RenderAsset, V4TimelineProps} from "./types";

const Media: React.FC<{asset: V4RenderAsset; fit: "contain" | "cover"; style?: React.CSSProperties}> = ({
  asset,
  fit,
  style,
}) => {
  const src = staticFile(asset.object_key);
  const merged = {width: "100%", height: "100%", objectFit: fit, ...style} as React.CSSProperties;
  if (asset.media_kind === "video") {
    return <Video src={src} style={merged} muted loop />;
  }
  return <Img src={src} style={merged} />;
};

const MultiAssetStage: React.FC<{
  effect: V4EffectProps;
  assets: Record<string, V4RenderAsset>;
  frame: number;
}> = ({effect, assets, frame}) => {
  const ordered = effect.ordered_items.length
    ? effect.ordered_items
    : Object.keys(effect.assets).map((name, index) => ({
        item_id: `${effect.effect_instance_id}:${name}`,
        asset_binding_name: name,
        member_key: null,
        start_frame: effect.start_frame,
        end_frame: effect.end_frame,
        hit_frame: effect.events[0]?.hit_frame ?? effect.start_frame,
      }));

  if (effect.effect_id === "before_after" && ordered.length >= 2) {
    const left = assets[effect.assets[ordered[0].asset_binding_name]];
    const right = assets[effect.assets[ordered[1].asset_binding_name]];
    const progress = Math.min(
      1,
      Math.max(0, (frame - (effect.events[0]?.hit_frame ?? effect.start_frame)) / Math.max(1, effect.events[0] ? effect.events[0].end_frame - effect.events[0].start_frame : 12)),
    );
    return (
      <div style={layoutBox(effect.layout)}>
        <div style={{position: "absolute", inset: 0, display: "flex", gap: 12}}>
          <div style={{flex: 1, overflow: "hidden", opacity: 1}}>{left ? <Media asset={left} fit={effect.layout.fit} /> : null}</div>
          <div style={{flex: 1, overflow: "hidden", opacity: 0.55 + 0.45 * progress}}>{right ? <Media asset={right} fit={effect.layout.fit} /> : null}</div>
        </div>
      </div>
    );
  }

  if (effect.effect_id === "grid_reveal") {
    return (
      <div style={layoutBox(effect.layout)}>
        <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, width: "100%", height: "100%"}}>
          {ordered.map((item) => {
            const asset = assets[effect.assets[item.asset_binding_name]];
            const visible = frame >= item.hit_frame;
            return (
              <div key={item.item_id} style={{opacity: visible ? 1 : 0.15, overflow: "hidden"}}>
                {asset ? <Media asset={asset} fit={effect.layout.fit} /> : null}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Default / gallery / sequence: show active ordered item by frame
  const active =
    [...ordered].reverse().find((item) => frame >= item.start_frame && frame < item.end_frame) ??
    ordered[0];
  const assetRef = active ? effect.assets[active.asset_binding_name] : effect.assets.primary;
  const asset = assetRef ? assets[assetRef] : undefined;
  return (
    <div style={layoutBox(effect.layout)}>
      {asset ? <Media asset={asset} fit={effect.layout.fit} /> : null}
    </div>
  );
};

export const V4Timeline: React.FC<V4TimelineProps> = (props) => {
  const frame = useCurrentFrame();
  const assets = Object.fromEntries(props.render_assets.map((item) => [item.asset_ref, item]));
  const effectById = Object.fromEntries(props.effect_props.map((item) => [item.effect_instance_id, item]));

  return (
    <AbsoluteFill style={{backgroundColor: "#070a0e"}}>
      {props.visual_tracks.map((track) =>
        track.clips.map((clip) => {
          if (frame < clip.start_frame || frame >= clip.end_frame) {
            return null;
          }
          const effect = effectById[clip.effect_instance_id];
          if (!effect) {
            throw new Error(`Missing effect_props for ${clip.effect_instance_id}`);
          }
          return (
            <Sequence
              key={clip.clip_id}
              from={clip.start_frame}
              durationInFrames={clip.end_frame - clip.start_frame}
              layout="none"
            >
              <AbsoluteFill style={{zIndex: clip.z_index}}>
                <EffectStage effect={effect} absoluteFrame={frame}>
                  <MultiAssetStage effect={effect} assets={assets} frame={frame} />
                </EffectStage>
              </AbsoluteFill>
            </Sequence>
          );
        }),
      )}
      <SubtitleTrack cues={props.subtitle_track} platform_profile={props.platform_profile} />
    </AbsoluteFill>
  );
};
