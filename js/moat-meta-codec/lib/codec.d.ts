/**
 * Type definitions for @moat/meta-codec.
 */

/**
 * Encode an array of elements to a MoaT metadata string.
 */
export function encode(data: unknown[]): string;

/**
 * Decode a MoaT metadata string to an array of elements.
 */
export function decode(data: string): unknown[];

/**
 * Encode a Node-RED message's MoaT metadata to the ``MoaT`` user property.
 */
export function encMsg(node: {
  moat?: Record<string, unknown>;
  userProperties?: Record<string, string>;
}): void;

/**
 * Decode a Node-RED message's ``MoaT`` user property to ``msg.moat``.
 */
export function decMsg(node: {
  moat?: Record<string, unknown>;
  userProperties?: Record<string, string>;
}): void;

/**
 * Node-RED node registration function (default export).
 */
declare function moatCodecInit(RED: unknown): void;
export default moatCodecInit;
