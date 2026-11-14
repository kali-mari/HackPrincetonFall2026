import { useState } from 'react'
import type { ScanMark } from '../scanning'
import type { Word } from '../data/symbols'
import styles from './Tile.module.css'

type TileProps = { word: Word; onSelect: (word: Word) => void; scanned?: ScanMark }

export default function Tile({ word, onSelect, scanned }: TileProps) {
  const [iconFailed, setIconFailed] = useState(false)
  // Words over 6 letters crowd the edge of a 120px tile at the large size.
  const fitsLarge = word.label.split(' ').every((part) => part.length <= 6)

  return (
    <button className={`${styles.tile} ${styles[word.wordType]}`} onClick={() => onSelect(word)} data-scan={scanned}>
      {iconFailed ? (
        <span className={fitsLarge ? styles.labelOnly : styles.label}>{word.label}</span>
      ) : (
        <>
          <img className={styles.icon} src={word.icon} alt="" onError={() => setIconFailed(true)} />
          <span className={styles.label}>{word.label}</span>
        </>
      )}
    </button>
  )
}
