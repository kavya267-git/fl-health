/** The two illustrations and their alt text, shared by the pages that show them. */
import networkUrl from './fl-network.webp'
import worldUrl from './fl-world.webp'

/** 1323 x 586. Shown where it carries meaning (sign-in, How it works), so it has alt text. */
export const NETWORK_IMAGE = {
  src: networkUrl,
  alt: 'Four hospitals, each keeping its own patient records, ECGs and X-rays, exchange model updates with a central coordinator.',
}

/** 592 x 380. Only decorates empty states, whose text says what is missing, so its alt text is empty. */
export const WORLD_IMAGE = { src: worldUrl, alt: '' }
