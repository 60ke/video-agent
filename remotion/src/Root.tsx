import React from "react";
import {Composition} from "remotion";
import {AgentTest, type AgentTestProps} from "./AgentTest";

const defaults: AgentTestProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  frame_count: 30,
  voice_path: "",
  title: "Agent Video Test",
  scenes: [],
  subtitles: [],
};

export const Root: React.FC = () => (
  <Composition
    id="AgentTest"
    component={AgentTest}
    defaultProps={defaults}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={30}
    calculateMetadata={({props}) => ({
      width: props.width,
      height: props.height,
      fps: props.fps,
      durationInFrames: props.frame_count,
    })}
  />
);
