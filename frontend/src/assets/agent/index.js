/** Screenshots of the MediFed Hospital Agent, for the "Connect your hospital" steps. */
import step1 from './step1.png'
import step2 from './step2.png'
import step3 from './step3.png'

export const AGENT_SHOTS = [
  {
    src: step1,
    title: 'Open the agent, paste the token',
    text: 'Unzip the download and open "MediFed Hospital Agent.exe". Check the server address, paste your node token and click "Check token": your hospital’s name appears.',
    alt: 'The agent window with the server address, the node token field and the hospital’s name after Check token.',
  },
  {
    src: step2,
    title: 'Choose your data folder, Check data',
    text: 'Click "Choose data folder…" (or "Use sample data (SIMULATED)" to try it) and then "Check data". The check runs on your computer; each kind of data shows passed or failed with record counts.',
    alt: 'The agent window after Check data, with a passed result and record counts for each kind of data.',
  },
  {
    src: step3,
    title: 'Connect',
    text: 'Click "Connect". The activity log shows the connection, round invitations, local training, the size of each update sent and the F1 of the new model on your data.',
    alt: 'The agent window while connected, with the activity log showing a round: invited, training, update sent, evaluated.',
  },
]
