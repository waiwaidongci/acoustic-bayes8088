import {runStates,reviewStates,planStates} from '../../constants/enums.js';import {esc} from '../../utils/format.js';
export function status(state){const map={...runStates,...reviewStates,...planStates};return '<span class="status '+esc(state)+'">'+esc(map[state]||state)+'</span>'}
