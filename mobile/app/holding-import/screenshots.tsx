import { router } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { useState } from 'react';
import { Image, Pressable, Text, View } from 'react-native';

import { Button, Card, Chip, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useUploadScreenshots, type PickedImage } from '@/hooks/useImports';
import { useAccounts } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';

const MAX_IMAGES = 5;
const MAX_BYTES = 8 * 1024 * 1024;

/**
 * 截图上传。后端立即回 202 + import_id，识别交给后台 worker 完成；
 * 本页只负责把这批图片提交出去（spec 7.9）。
 */
export default function ScreenshotImportScreen() {
  const accounts = useAccounts();
  const upload = useUploadScreenshots();
  const viewAccount = useUiStore((state) => state.accountId);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [images, setImages] = useState<PickedImage[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  // 顶部导航选中的账户就是导入目标；这里另选的账户只改写本表单，
  // 而“全部账户”视图本身不是合法的导入目标。
  const chosen = accountId ?? viewAccount ?? accounts.data?.items[0]?.id ?? null;

  async function pick() {
    setProblem(null);
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setProblem('需要相册权限才能读取持仓截图');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsMultipleSelection: true,
      quality: 1,
    });
    if (result.canceled || !result.assets?.length) return;

    const picked: PickedImage[] = result.assets.map((asset) => ({
      uri: asset.uri,
      name: asset.fileName ?? `holding-${Date.now()}-${images.length}.jpg`,
      mimeType: asset.mimeType ?? 'image/jpeg',
    }));
    const oversized = result.assets.filter((asset) => (asset.fileSize ?? 0) > MAX_BYTES);
    if (oversized.length > 0) {
      setProblem(`${oversized.length} 张图片超过 8MB，请先压缩后再上传`);
      return;
    }
    const merged = [...images, ...picked];
    if (merged.length > MAX_IMAGES) {
      setProblem(`一次最多上传 ${MAX_IMAGES} 张截图`);
      return;
    }
    setImages(merged);
  }

  function submit() {
    setProblem(null);
    if (chosen === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    if (images.length === 0) {
      setProblem('请至少选择一张持仓截图');
      return;
    }
    upload.mutate(
      { accountId: chosen, images },
      {
        onSuccess: (accepted) => router.replace(`/holding-import/${accepted.import_id}`),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  return (
    <Screen>
      <Card>
        <SectionTitle title="识别账户" />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {(accounts.data?.items ?? []).map((account) => (
            <Chip key={account.id} label={account.name} active={chosen === account.id} onPress={() => setAccountId(account.id)} />
          ))}
          <Chip label="+ 新增账户" onPress={() => router.push('/account/add')} />
        </View>
      </Card>

      <Card>
        <SectionTitle title={`截图（${images.length}/${MAX_IMAGES}）`} />
        <Text style={{ fontSize: 12, color: theme.textMuted, marginBottom: 10 }}>
          支持多张：按基金代码去重合并，单张失败不影响其余结果。点图片右上角可移除这一张。
        </Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {images.map((image, index) => (
            <Pressable
              key={image.uri}
              accessibilityRole="button"
              accessibilityLabel={`移除第 ${index + 1} 张截图`}
              hitSlop={10}
              onPress={() => setImages((current) => current.filter((item) => item.uri !== image.uri))}
              style={({ pressed }) => [
                {
                  width: 96,
                  height: 128,
                  marginRight: 8,
                  marginBottom: 8,
                  borderRadius: 8,
                  opacity: pressed ? 0.85 : 1,
                },
              ]}
            >
              <Image source={{ uri: image.uri }} style={{ width: '100%', height: '100%', borderRadius: 8 }} />
              <View
                style={{
                  position: 'absolute',
                  top: 4,
                  right: 4,
                  width: 20,
                  height: 20,
                  borderRadius: 10,
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: 'rgba(17,24,39,0.55)',
                }}
              >
                <Text style={{ color: '#FFFFFF', fontSize: 11, lineHeight: 13 }}>✕</Text>
              </View>
            </Pressable>
          ))}
        </View>
        <Button label="选择截图" variant="secondary" onPress={pick} />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginTop: 12 }}>{problem}</Text> : null}
        <View style={{ marginTop: 10 }}>
          <Button label="开始识别" onPress={submit} loading={upload.isPending} />
        </View>
      </Card>
    </Screen>
  );
}
