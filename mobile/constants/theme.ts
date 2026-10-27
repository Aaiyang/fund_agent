/**
 * 应用调色板：米白纸感底、墨绿主色、金棕点缀。
 *
 * 数据颜色仍按中国市场惯例红涨绿跌，与主色互不替代：主色负责交互，
 * 红绿只负责钱的方向。
 */

import { Platform } from 'react-native';

/** 欢迎页与少量大标题用宋体系，正文仍走系统无衬线，保证小字号清晰。 */
const displayFont = Platform.select({
  ios: 'Songti SC',
  android: 'serif',
  default: '"Noto Serif SC", "Songti SC", "STSong", "SimSun", serif',
});

const monoFont = Platform.select({
  ios: 'Menlo',
  android: 'monospace',
  default: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
});

export const theme = {
  background: '#F2F1E8',
  surface: '#FFFDF7',
  surfaceStrong: '#FFFEF9',
  surfaceSoft: 'rgba(46, 91, 61, 0.035)',
  surfaceMuted: '#EDF1E7',
  border: 'rgba(43, 80, 56, 0.13)',
  borderStrong: 'rgba(43, 80, 56, 0.22)',
  text: '#263C30',
  textSoft: '#465E4E',
  textMuted: '#596D5D',
  textFaint: '#6F8577',
  primary: '#2F7057',
  primaryStrong: '#265E48',
  primarySoft: 'rgba(47, 112, 87, 0.08)',
  primaryInk: '#FFFFFF',
  gold: '#806333',
  goldStrong: '#6B5027',
  goldSoft: 'rgba(128, 99, 51, 0.08)',
  up: '#C43D32',
  down: '#2E7654',
  flat: '#596D5D',
  warning: '#91601A',
  warningBackground: '#F3E8CF',
  warningSoft: 'rgba(145, 96, 26, 0.08)',
  danger: '#B6424B',
  dangerSoft: 'rgba(182, 66, 75, 0.07)',
  success: '#2E7654',
  successSoft: 'rgba(46, 118, 84, 0.10)',
  overlay: 'rgba(24, 38, 30, 0.42)',
  skeleton: 'rgba(38, 60, 48, 0.06)',
  codeBackground: '#20362C',
  codeText: '#DDE9DF',
  inlineCodeBackground: 'rgba(47, 112, 87, 0.07)',
  tableHeader: '#EDF1E7',
  tableStripe: '#F8F6EC',
  radius: 16,
  radiusSm: 10,
  radiusLg: 22,
  gap: 12,
  displayFont,
  monoFont,
  cardShadow: {
    shadowColor: '#213A2A',
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
} as const;
