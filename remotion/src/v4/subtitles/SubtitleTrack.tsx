import React from "react";
import {AbsoluteFill, useCurrentFrame} from "remotion";
import type {V4PlatformProfileProps, V4SubtitleCue} from "../types";

export const SubtitleTrack: React.FC<{
  cues: V4SubtitleCue[];
  platform_profile: V4PlatformProfileProps;
}> = ({cues, platform_profile}) => {
  const frame = useCurrentFrame();
  const active = cues.filter((cue) => frame >= cue.start_frame && frame < cue.end_frame);
  const fontPx = platform_profile.subtitle_font_px;
  return (
    <AbsoluteFill>
      {active.map((cue) => {
        const slot =
          cue.slot_id === "subtitle_top"
            ? platform_profile.subtitle_top
            : platform_profile.subtitle_lower;
        const color = cue.style_id === "gallery_yellow" ? "#ffd629" : "#ffffff";
        return (
          <div
            key={cue.cue_id}
            style={{
              position: "absolute",
              top: slot.y,
              left: slot.x,
              width: slot.w,
              color,
              fontFamily: "Noto Sans CJK SC, Microsoft YaHei, sans-serif",
              fontWeight: 800,
              fontSize: fontPx,
              lineHeight: 1.15,
              textAlign: "center",
              textShadow: "2px 3px 0 #111",
              whiteSpace: "nowrap",
              overflow: "hidden",
            }}
          >
            {cue.emphasize_text && cue.text.includes(cue.emphasize_text) ? (
              <>
                {cue.text.slice(0, cue.text.indexOf(cue.emphasize_text))}
                <span style={{color: "#ffd629"}}>{cue.emphasize_text}</span>
                {cue.text.slice(cue.text.indexOf(cue.emphasize_text) + cue.emphasize_text.length)}
              </>
            ) : (
              cue.text
            )}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
