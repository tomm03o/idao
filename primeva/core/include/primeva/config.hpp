// Primeva — engine-agnostic simulation core.
// Global, compile-time world constants. Every system derives its sizes from here.
#pragma once

#include <cstdint>

namespace primeva {

// --- Voxel grid ------------------------------------------------------------
// 0.125 m voxels: 8 voxels per metre. Chosen from first principles:
//  * small enough that smooth (SDF) meshing reads as natural terrain at 1-2 m
//    view distance and that a human-scale tunnel (2 m) is 16 voxels across;
//  * power of two so LOD levels (0.25, 0.5, 1, 2 ... m) align exactly;
//  * large enough that a 32^3 chunk (4 m) keeps chunk counts tractable.
inline constexpr double kVoxelSize = 0.125;           // metres, LOD 0
inline constexpr double kVoxelsPerMetre = 1.0 / kVoxelSize;
inline constexpr int kChunkShift = 5;                   // 32 voxels
inline constexpr int kChunkSize = 1 << kChunkShift;     // voxels per chunk edge
inline constexpr int kChunkMask = kChunkSize - 1;
inline constexpr int kChunkVolume = kChunkSize * kChunkSize * kChunkSize;
inline constexpr double kChunkWorldSize = kChunkSize * kVoxelSize;  // 4 m

// --- Signed distance quantisation -------------------------------------------
// Voxels store the signed distance to the nearest solid surface, negative
// inside solid matter. One int8 step = 1/16 voxel, giving a ±~7.9 voxel
// (≈ ±1 m) band, which is everything Surface Nets and CSG edits need.
inline constexpr int kSdfStepsPerVoxel = 16;
inline constexpr int kSdfMax = 127;
inline constexpr int kSdfMin = -127;

// --- Vertical extent ---------------------------------------------------------
// Sea level is y = 0. Bedrock (indestructible) floor at -2000 m; the generator
// produces terrain up to +4800 m. In voxels this is [-16000, 38400], far inside
// int32 range; horizontal extent of a 1100 km world is 8.8e6 voxels.
inline constexpr double kSeaLevelM = 0.0;
inline constexpr double kBedrockTopM = -2000.0;
inline constexpr double kWorldMinYM = -2048.0;
inline constexpr double kWorldMaxYM = 4864.0;

}  // namespace primeva
