import React, { useMemo } from 'react';
import { diffLines, type Change } from 'diff';

interface DiffViewerProps {
    oldText: string;
    newText: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ oldText, newText }) => {
    const diff = useMemo(() => diffLines(oldText, newText), [oldText, newText]);

    return (
        <div className="diff-viewer">
            {diff.map((part: Change, index: number) => {
                const color = part.added ? '#2e4b33' : part.removed ? '#4b2e2e' : 'transparent';
                const textColor = part.added ? '#a8e6a3' : part.removed ? '#e6a3a3' : 'inherit';
                const prefix = part.added ? '+ ' : part.removed ? '- ' : '  ';

                return (
                    <div
                        key={index}
                        style={{ backgroundColor: color, color: textColor, whiteSpace: 'pre-wrap', fontFamily: 'monospace' }}
                    >
                        {part.value.split('\n').map((line, i) => {
                            if (line === '') return null; // Skip empty lines mostly or handle them?
                            return <div key={i}>{prefix}{line}</div>
                        })}
                    </div>
                );
            })}
        </div>
    );
};
