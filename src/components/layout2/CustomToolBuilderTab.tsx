/**
 * CustomToolBuilderTab — wraps the full CustomToolBuilder into a layout2 workspace tab.
 */
import { useLayoutState, type Tab } from './useLayout';
import CustomToolBuilder from '../../features/tools/ui/CustomToolBuilder';

interface Props { tab: Tab }

export default function CustomToolBuilderTab({ tab }: Props) {
  const { closeTab, openTab } = useLayoutState();
  const { existingToolId, skipTemplateStep, initialTemplate } = tab.data ?? {};

  const handleClose = () => closeTab(tab.id);
  const handleBack = () => {
    closeTab(tab.id);
    openTab({ id: 'tools-list', label: 'Tools', viewType: 'tool-category', data: {} });
  };

  return (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <style>{`
        .uniform-builder {
          font-size: 13px;
        }
        .uniform-builder * {
          font-size: 13px !important;
          font-weight: 400 !important;
        }
      `}</style>
      <div className="uniform-builder">
        <CustomToolBuilder
          onClose={handleClose}
          onBack={handleBack}
          existingToolId={existingToolId}
          skipTemplateStep={skipTemplateStep}
          initialTemplate={initialTemplate}
        />
      </div>
    </div>
  );
}